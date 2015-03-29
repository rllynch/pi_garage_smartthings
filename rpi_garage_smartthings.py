#!/usr/bin/python2.7

""" RPi Garage Monitor for SmartThings

Copyright 2015 Richard L. Lynch <rich@richlynch.com>

Description: Monitor a garage door open/closed sensor attached to a Raspberry Pi
GPIO and update a SmartThings hub with its status. Multiple instances of this
program may be run in parallel if there are multiple garage doors.

Dependencies: python-twisted, python-rpi.gpio

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
this file except in compliance with the License. You may obtain a copy of the
License at:

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""

import argparse
import logging
from time import time
from twisted.web import server, resource
from twisted.internet import reactor
from twisted.internet.defer import succeed
from twisted.internet.protocol import DatagramProtocol
from twisted.web.client import Agent
from twisted.web.http_headers import Headers
from twisted.web.iweb import IBodyProducer
from twisted.web._newclient import ResponseFailed
from zope.interface import implements

SSDP_PORT = 1900
SSDP_ADDR = '239.255.255.250'
UUID = 'd1c58eb4-9220-11e4-96fa-123b93f75cba'
SEARCH_RESPONSE = 'HTTP/1.1 200 OK\r\nCACHE-CONTROL:max-age=30\r\nEXT:\r\nLOCATION:%s\r\nSERVER:Linux, UPnP/1.0, Pi_Garage/1.0\r\nST:%s\r\nUSN:uuid:%s::%s'

def determine_ip_for_host(host):
    """Determine local IP address used to communicate with a particular host"""
    test_sock = DatagramProtocol()
    test_sock_listener = reactor.listenUDP(0, test_sock) # pylint: disable=no-member
    test_sock.transport.connect(host, 1900)
    my_ip = test_sock.transport.getHost().host
    test_sock_listener.stopListening()
    return my_ip

class StringProducer(object):
    """Writes an in-memory string to a Twisted request"""
    implements(IBodyProducer)

    def __init__(self, body):
        self.body = body
        self.length = len(body)

    def startProducing(self, consumer): # pylint: disable=invalid-name
        """Start producing supplied string to the specified consumer"""
        consumer.write(self.body)
        return succeed(None)

    def pauseProducing(self): # pylint: disable=invalid-name
        """Pause producing - no op"""
        pass

    def stopProducing(self): # pylint: disable=invalid-name
        """ Stop producing - no op"""
        pass

class SSDPServer(DatagramProtocol):
    """Receive and response to M-SEARCH discovery requests from SmartThings hub"""

    def __init__(self, interface='', status_port=0, device_target=''):
        self.interface = interface
        self.device_target = device_target
        self.status_port = status_port
        self.port = reactor.listenMulticast(SSDP_PORT, self, listenMultiple=True) # pylint: disable=no-member
        self.port.joinGroup(SSDP_ADDR, interface=interface)
        reactor.addSystemEventTrigger('before', 'shutdown', self.stop) # pylint: disable=no-member

    def datagramReceived(self, data, (host, port)):
        try:
            header, _ = data.split('\r\n\r\n')[:2]
        except ValueError:
            return
        lines = header.split('\r\n')
        cmd = lines.pop(0).split(' ')
        lines = [x.replace(': ', ':', 1) for x in lines]
        lines = [x for x in lines if len(x) > 0]
        headers = [x.split(':', 1) for x in lines]
        headers = dict([(x[0].lower(), x[1]) for x in headers])

        logging.debug('SSDP command %s %s - from %s:%d with headers %s', cmd[0], cmd[1], host, port, headers)

        search_target = ''
        if 'st' in headers:
            search_target = headers['st']

        if cmd[0] == 'M-SEARCH' and cmd[1] == '*' and search_target in self.device_target:
            logging.info('Received %s %s for %s from %s:%d', cmd[0], cmd[1], search_target, host, port)
            url = 'http://%s:%d/status' % (determine_ip_for_host(host), self.status_port)
            response = SEARCH_RESPONSE % (url, search_target, UUID, self.device_target)
            self.port.write(response, (host, port))
        else:
            logging.debug('Ignored SSDP command %s %s', cmd[0], cmd[1])

    def stop(self):
        """Leave multicast group and stop listening"""
        self.port.leaveGroup(SSDP_ADDR, interface=self.interface)
        self.port.stopListening()

class StatusServer(resource.Resource):
    """HTTP server that serves the status of the garage door to the
       SmartThings hub"""
    isLeaf = True
    def __init__(self, device_target, subscription_list, garage_door_status):
        self.device_target = device_target
        self.subscription_list = subscription_list
        self.garage_door_status = garage_door_status
        resource.Resource.__init__(self)

    def render_SUBSCRIBE(self, request): # pylint: disable=invalid-name
        """Handle subscribe requests from ST hub - hub wants to be notified of
           garage door status updates"""
        headers = request.getAllHeaders()
        logging.debug("SUBSCRIBE: %s", headers)
        if 'callback' in headers:
            cb_url = headers['callback'][1:-1]

            if not cb_url in self.subscription_list:
                self.subscription_list[cb_url] = {}
                logging.info('Added subscription %s', cb_url)
            else:
                logging.info('Refreshed subscription %s', cb_url)
            self.subscription_list[cb_url]['expiration'] = time() + 24 * 3600

        if self.garage_door_status['last_state'] == 'closed':
            cmd = 'status-closed'
        else:
            cmd = 'status-open'
        msg = '<msg><cmd>%s</cmd><usn>uuid:%s::%s</usn></msg>' % (cmd, UUID, self.device_target)
        return msg

    def render_GET(self, request): # pylint: disable=invalid-name
        """Handle polling requests from ST hub"""
        if request.path == '/status':
            if self.garage_door_status['last_state'] == 'closed':
                cmd = 'status-closed'
            else:
                cmd = 'status-open'
            msg = '<msg><cmd>%s</cmd><usn>uuid:%s::%s</usn></msg>' % (cmd, UUID, self.device_target)
            logging.info("Polling request from %s for %s - returned %s",
                         request.getClientIP(),
                         request.path,
                         cmd)
            return msg
        else:
            logging.info("Received bogus request from %s for %s",
                         request.getClientIP(),
                         request.path)
            return ""

class GarageMonitor(object):
    """Monitors a garage door status, generating notifications whenever its
       state changes"""
    def __init__(self, device_target, subscription_list, polling_freq, gpio_pin, garage_door_status): # pylint: disable=too-many-arguments
        self.device_target = device_target
        self.subscription_list = subscription_list
        self.polling_freq = polling_freq
        self.gpio_pin = gpio_pin
        self.garage_door_status = garage_door_status

        # Simulation only variables
        self.countdown = 3

        # Configure GPIO
        if self.gpio_pin >= 0:
            # Don't import this for simulation mode
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BOARD)
            GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        reactor.callLater(self.polling_freq, self.check_garage_state, None) # pylint: disable=no-member

    def get_current_state(self):
        """Get the current state of the garage door as a string"""
        if self.gpio_pin < 0:
            # Simulation mode - alternate between open and closed
            self.countdown -= 1
            if self.countdown <= 0:
                self.countdown = 3
                if self.garage_door_status['last_state'] == 'closed':
                    return 'open'
                else:
                    return 'closed'
            return self.garage_door_status['last_state']
        else:
            # Read GPIO pin
            import RPi.GPIO as GPIO
            if GPIO.input(self.gpio_pin):
                state = 'open'
            else:
                state = 'closed'

            return state

    def check_garage_state(self, _):
        """Called periodically to check if the garage door has changed state"""
        current_state = self.get_current_state()
        if current_state != self.garage_door_status['last_state']:
            logging.info('State changed from %s to %s', self.garage_door_status['last_state'], current_state)
            self.garage_door_status['last_state'] = current_state
            self.notify_hubs()

        # Schedule next check
        reactor.callLater(self.polling_freq, self.check_garage_state, None) # pylint: disable=no-member

    def notify_hubs(self):
        """Notify the subscribed SmartThings hubs that a state change has
           occurred"""
        if self.garage_door_status['last_state'] == 'closed':
            cmd = 'status-closed'
        else:
            cmd = 'status-open'
        for subscription in self.subscription_list:
            if self.subscription_list[subscription]['expiration'] > time():
                logging.info("Notifying hub %s", subscription)
                msg = '<msg><cmd>%s</cmd><usn>uuid:%s::%s</usn></msg>' % (cmd, UUID, self.device_target)
                body = StringProducer(msg)
                agent = Agent(reactor)
                req = agent.request(
                    'POST',
                    subscription,
                    Headers({'CONTENT-LENGTH': [len(msg)]}),
                    body)
                req.addCallback(self.handle_response)
                req.addErrback(self.handle_error)

    def handle_response(self, response): # pylint: disable=no-self-use
        """Handle the SmartThings hub returning a status code to the POST.
           This is actually unexpected - it typically closes the connection
           for POST/PUT without giving a response code."""
        logging.error("Unexpected response code: %d", response.code)

    def handle_error(self, response): # pylint: disable=no-self-use
        """Handle errors generating performing the NOTIFY. There doesn't seem
           to be a way to avoid ResponseFailed - the SmartThings Hub
           doesn't generate a proper response code for POST or PUT, and if
           NOTIFY is used, it ignores the body."""
        if isinstance(response.value, ResponseFailed):
            logging.debug("Response failed (expected)")
        else:
            logging.error("Unexpected response: %s", response)

def main():
    """Main function to handle use from command line"""

    arg_proc = argparse.ArgumentParser(description='Provides a garage door open/closed status to a SmartThings hub')
    arg_proc.add_argument('--httpport', dest='http_port', help='HTTP port number', default=8080, type=int)
    arg_proc.add_argument('--deviceindex', dest='device_index', help='Device index', default=1, type=int)
    arg_proc.add_argument('--pollingfreq', dest='polling_freq', help='Number of seconds between polling garage door state', default=5, type=int)
    arg_proc.add_argument('--gpiopin', dest='gpio_pin', help='GPIO pin number', default=-1, type=int)
    arg_proc.add_argument('--debug', dest='debug', help='Enable debug messages', default=False, action='store_true')
    options = arg_proc.parse_args()

    device_target = 'urn:schemas-upnp-org:device:RPi_Garage_Monitor:%d' % (options.device_index)
    log_level = logging.INFO
    if options.debug:
        log_level = logging.DEBUG

    logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s', level=log_level)

    subscription_list = {}
    garage_door_status = {'last_state': 'unknown'}

    logging.info('Initializing garage door monitor')

    # SSDP server to handle discovery
    SSDPServer(status_port=options.http_port, device_target=device_target)

    # Monitor garage door state and send notifications on state change
    GarageMonitor(device_target=device_target,
                  subscription_list=subscription_list,
                  polling_freq=options.polling_freq,
                  gpio_pin=options.gpio_pin,
                  garage_door_status=garage_door_status)

    # HTTP site to handle subscriptions/polling
    status_site = server.Site(StatusServer(device_target, subscription_list, garage_door_status))
    reactor.listenTCP(options.http_port, status_site) # pylint: disable=no-member

    logging.info('Initialization complete')

    if options.gpio_pin < 0:
        logging.warn('Simulation mode active')

    reactor.run() # pylint: disable=no-member

if __name__ == "__main__":
    main()

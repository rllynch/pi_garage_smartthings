/**
 *  RPi Garage Connect
 *
 *  Copyright 2015 Richard L. Lynch <rich@richlynch.com>
 *
 *  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
 *  in compliance with the License. You may obtain a copy of the License at:
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
 *  on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License
 *  for the specific language governing permissions and limitations under the License.
 *
 */

definition(
    name: "RPi Garage Connect",
    namespace: "rpi_garage",
    author: "Richard L. Lynch",
    description: "RPi Garage Connection",
    category: "SmartThings Labs",
    iconUrl: "https://s3.amazonaws.com/smartapp-icons/Convenience/Cat-Convenience.png",
    iconX2Url: "https://s3.amazonaws.com/smartapp-icons/Convenience/Cat-Convenience@2x.png",
    iconX3Url: "https://s3.amazonaws.com/smartapp-icons/Convenience/Cat-Convenience@2x.png")

preferences {
    page(name:"selectPiPage", title:"Configuration", content:"selectPiPage")
}

/* Preferences page to be shown when installing app */
def selectPiPage() {
    def refreshInterval = 5

    if(!state.subscribe) {
        log.debug('Subscribing to updates')
        // subscribe to M-SEARCH answers from hub
        subscribe(location, null, locationHandler, [filterEvents:false])
        state.subscribe = true
    }

    // Perform M-SEARCH
    log.debug('Performing discovery')
    sendHubCommand(new physicalgraph.device.HubAction("lan discovery urn:schemas-upnp-org:device:RPi_Garage_Monitor:", physicalgraph.device.Protocol.LAN))

    def devicesForDialog = getDevicesForDialog()

    // Only one page - can install or uninstall from this page
    return dynamicPage(name:"selectPiPage", title:"", nextPage:"", refreshInterval: refreshInterval, install:true, uninstall: true) {
        section("") {
            input "selectedRPi", "enum", required:false, title:"Select Raspberry Pi \n(${devicesForDialog.size() ?: 0} found)", multiple:true, options:devicesForDialog
        }
    }
}

/* Generate the list of devices for the preferences dialog */
def getDevicesForDialog() {
    def devices = getDevices()
    def map = [:]
    devices.each {
        def value = convertHexToIP(it.value.ip) + ':' + convertHexToInt(it.value.port)
        def key = it.value.ssdpUSN.toString()
        map["${key}"] = value
    }
    map
}

/* Get map containing discovered devices. Maps USN to parsed event. */
def getDevices() {
    if (!state.devices) { state.devices = [:] }
    log.debug("There are ${state.devices.size()} devices at this time")
    state.devices
}

/* Callback when an M-SEARCH answer is received */
def locationHandler(evt) {
    if(evt.name == "ping") {
        return ""
    }

    log.debug('RPi Garage App Received Response: ' + evt.description)

    def description = evt.description
    def hub = evt?.hubId
    def parsedEvent = parseDiscoveryMessage(description)
    parsedEvent << ["hub":hub]

    if (parsedEvent?.ssdpTerm?.contains("schemas-upnp-org:device:RPi_Garage_Monitor:")) {
        def devices = getDevices()

        if (!(devices."${parsedEvent.ssdpUSN.toString()}")) { //if it doesn't already exist
            //log.debug('Parsed Event: ' + parsedEvent)
            devices << ["${parsedEvent.ssdpUSN.toString()}":parsedEvent]
        } else { // just update the values
            def d = devices."${parsedEvent.ssdpUSN.toString()}"
            boolean deviceChangedValues = false

            if(d.ip != parsedEvent.ip || d.port != parsedEvent.port) {
                d.ip = parsedEvent.ip
                d.port = parsedEvent.port
                deviceChangedValues = true
            }

            if (deviceChangedValues) {
                def children = getAllChildDevices()
                children.each {
                    if (it.getDeviceDataByName("ssdpUSN") == parsedEvent.ssdpUSN) {
                        //it.subscribe(parsedEvent.ip, parsedEvent.port)
                    }
                }
            }

        }
    }
}

def installed() {
    // remove location subscription
    unsubscribe()
    state.subscribe = false

    log.debug "Installed with settings: ${settings}"

    initialize()
}

def updated() {
    log.debug "Updated with settings: ${settings}"

    unsubscribe()
    initialize()
}

def initialize() {
    log.debug('Initializing')

    selectedRPi.each { ssdpUSN ->
        def devices = getDevices()

        // Make the dni the MAC followed by the index from the USN, unless it's the USN ending in :1
        // that device has just the MAC address as its DNI and receives all the notifications from
        // the RPi
        def dni = devices[ssdpUSN].mac + ':' + ssdpUSN.split(':').last()

        if (ssdpUSN.endsWith(":1")) {
            dni = devices[ssdpUSN].mac
        }

        // Check if child already exists
        def d = getAllChildDevices()?.find {
            it.device.deviceNetworkId == dni
        }

        if (!d) {
            def ip = devices[ssdpUSN].ip
            def port = devices[ssdpUSN].port
            log.debug("Adding ${dni} for ${ssdpUSN} / ${ip}:${port}")
            d = addChildDevice("rpi_garage", "RPi Garage Monitor", dni, devices[ssdpUSN].hub, [
                "label": convertHexToIP(ip) + ':' + convertHexToInt(port),
                "data": [
                    "ip": ip,
                    "port": port,
                    "ssdpUSN": ssdpUSN,
                    "ssdpPath": devices[ssdpUSN].ssdpPath
                ]
            ])
        }
    }

    // Subscribe immediately, then once every ten minutes
    unschedule()
    schedule("0 0/10 * * * ?", subscribeToDevices)
    subscribeToDevices()
}

def subscribeToDevices() {
    log.debug "subscribeToDevices() called"
    def devices = getAllChildDevices()
    devices.each { d ->
        //log.debug('Call subscribe on '+d.id)
        d.subscribe()
    }
}

private def parseDiscoveryMessage(String description) {
    def device = [:]
    def parts = description.split(',')
    parts.each { part ->
        part = part.trim()
        if (part.startsWith('devicetype:')) {
            def valueString = part.split(":")[1].trim()
            device.devicetype = valueString
        } else if (part.startsWith('mac:')) {
            def valueString = part.split(":")[1].trim()
            if (valueString) {
                device.mac = valueString
            }
        } else if (part.startsWith('networkAddress:')) {
            def valueString = part.split(":")[1].trim()
            if (valueString) {
                device.ip = valueString
            }
        } else if (part.startsWith('deviceAddress:')) {
            def valueString = part.split(":")[1].trim()
            if (valueString) {
                device.port = valueString
            }
        } else if (part.startsWith('ssdpPath:')) {
            def valueString = part.split(":")[1].trim()
            if (valueString) {
                device.ssdpPath = valueString
            }
        } else if (part.startsWith('ssdpUSN:')) {
            part -= "ssdpUSN:"
            def valueString = part.trim()
            if (valueString) {
                device.ssdpUSN = valueString
            }
        } else if (part.startsWith('ssdpTerm:')) {
            part -= "ssdpTerm:"
            def valueString = part.trim()
            if (valueString) {
                device.ssdpTerm = valueString
            }
        } else if (part.startsWith('headers')) {
            part -= "headers:"
            def valueString = part.trim()
            if (valueString) {
                device.headers = valueString
            }
        } else if (part.startsWith('body')) {
            part -= "body:"
            def valueString = part.trim()
            if (valueString) {
                device.body = valueString
            }
        }
    }

    device
}

/* Convert hex (e.g. port number) to decimal number */
private Integer convertHexToInt(hex) {
    Integer.parseInt(hex,16)
}

/* Convert internal hex representation of IP address to dotted quad */
private String convertHexToIP(hex) {
    [convertHexToInt(hex[0..1]),convertHexToInt(hex[2..3]),convertHexToInt(hex[4..5]),convertHexToInt(hex[6..7])].join(".")
}

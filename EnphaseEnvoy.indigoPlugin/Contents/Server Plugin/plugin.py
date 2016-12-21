#! /usr/bin/env python2.6
# -*- coding: utf-8 -*-

"""
Enphase Indigo Plugin
Authors: GlennNZ

Enphase Plugin

"""

import datetime
import simplejson
import time as t
import requests
import urllib2
import os
import shutil
import flatdict
from ghpu import GitHubPluginUpdater
from requests.auth import HTTPDigestAuth

try:
    import indigo
except:
    pass

# Establish default plugin prefs; create them if they don't already exist.
kDefaultPluginPrefs = {
    u'configMenuPollInterval': "300",  # Frequency of refreshes.
    u'configMenuServerTimeout': "15",  # Server timeout limit.
    # u'refreshFreq': 300,  # Device-specific update frequency
    u'showDebugInfo': False,  # Verbose debug logging?
    u'configUpdaterForceUpdate': False,
    u'configUpdaterInterval': 24,
    u'showDebugLevel': "1",  # Low, Medium or High debug output.
    u'updaterEmail': "",  # Email to notify of plugin updates.
    u'updaterEmailsEnabled': False  # Notification of plugin updates wanted.
}


class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.debugLog(u"Initializing Enphase plugin.")

        self.debug = self.pluginPrefs.get('showDebugInfo', False)
        self.debugLevel = self.pluginPrefs.get('showDebugLevel', "1")
        self.deviceNeedsUpdated = ''
        self.prefServerTimeout = int(self.pluginPrefs.get('configMenuServerTimeout', "15"))
        self.updater = GitHubPluginUpdater(self)
        self.configUpdaterInterval = self.pluginPrefs.get('configUpdaterInterval', 24)
        self.configUpdaterForceUpdate = self.pluginPrefs.get('configUpdaterForceUpdate', False)

        # Convert old debugLevel scale to new scale if needed.
        # =============================================================
        if not isinstance(self.pluginPrefs['showDebugLevel'], int):
            if self.pluginPrefs['showDebugLevel'] == "High":
                self.pluginPrefs['showDebugLevel'] = 3
            elif self.pluginPrefs['showDebugLevel'] == "Medium":
                self.pluginPrefs['showDebugLevel'] = 2
            else:
                self.pluginPrefs['showDebugLevel'] = 1

    def __del__(self):
        if self.debugLevel >= 2:
            self.debugLog(u"__del__ method called.")
        indigo.PluginBase.__del__(self)

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if self.debugLevel >= 2:
            self.debugLog(u"closedPrefsConfigUi() method called.")

        if userCancelled:
            self.debugLog(u"User prefs dialog cancelled.")

        if not userCancelled:
            self.debug = valuesDict.get('showDebugInfo', False)
            self.debugLevel = self.pluginPrefs.get('showDebugLevel', "1")
            self.debugLog(u"User prefs saved.")

            if self.debug:
                indigo.server.log(u"Debugging on (Level: {0})".format(self.debugLevel))
            else:
                indigo.server.log(u"Debugging off.")

            if int(self.pluginPrefs['showDebugLevel']) >= 3:
                self.debugLog(u"valuesDict: {0} ".format(valuesDict))

        return True

    # Start 'em up.
    def deviceStartComm(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u"deviceStartComm() method called.")
        indigo.server.log(u"Starting Enphase/Envoy device: " + dev.name)

        #self.errorLog(unicode(dev.model))

        # CHECK IF PANEL - IF PANEL START OFFLINE
        # IF ENVOY START ONLINE
        if dev.model=='Enphase Panel':
            #self.errorLog(' Enphase Panel')
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.stateListOrDisplayStateIdChanged()
            return
        #dev.stateListOrDisplayStateIdChanged()
        dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
        dev.stateListOrDisplayStateIdChanged()


# Default Indigo Plugin StateList
# This overrides and pulls the current state list (from devices.xml and then adds whatever to it via these calls
# http://forums.indigodomo.com/viewtopic.php?f=108&t=12898
# for summary
# Issue being that with trigger and control page changes will add the same to all devices unless check what device within below call - should be an issue for this plugin
# """"
#     def getDeviceStateList(self,dev):
#         if self.debugLevel>=2:
#             self.debugLog(u'getDeviceStateList called')
#
#         stateList = indigo.PluginBase.getDeviceStateList(self, dev)
#         if stateList is not None:
#             # Add any dynamic states onto the device based on the node's characteristics.
#                 someNumState = self.getDeviceStateDictForNumberType(u"someNumState", u"Some Level Label",
#                                                                     u"Some Level Label")
#                 someStringState = self.getDeviceStateDictForStringType(u"someStringState", u"Some Level Label",
#                                                                        u"Some Level Label")
#                 someOnOffBoolState = self.getDeviceStateDictForBoolOnOffType(u"someOnOffBoolState", u"Some Level Label",
#                                                                              u"Some Level Label")
#                 someYesNoBoolState = self.getDeviceStateDictForBoolYesNoType(u"someYesNoBoolState", u"Some Level Label",
#                                                                              u"Some Level Label")
#                 someOneZeroBoolState = self.getDeviceStateDictForBoolOneZeroType(u"someOneZeroBoolState",
#                                                                                  u"Some Level Label",
#                                                                                  u"Some Level Label")
#                 someTrueFalseBoolState = self.getDeviceStateDictForBoolTrueFalseType(u"someTrueFalseBoolState",
#                                                                                      u"Some Level Label",
#                                                                                      u"Some Level Label")
#                 stateList.append(someNumState)
#                 stateList.append(someStringState)
#                 stateList.append(someOnOffBoolState)
#                 stateList.append(someYesNoBoolState)
#                 stateList.append(someOneZeroBoolState)
#                 stateList.append(someTrueFalseBoolState)
#                 try:
#
#                     if self.PanelDict is not None:
#                         x=0
#                         for array in self.PanelDict:
#                             numberArray = "Panel"+str(x)
#                             Statearray = self.getDeviceStateDictForNumberType(numberArray,numberArray,numberArray)
#                             stateList.append(Statearray)
#                             x=x+1
#                 except Exception as error:
#                     self.errorLog(unicode('error in statelist Panel:'+error.message))
#         return stateList
# """"


    # Shut 'em down.
    def deviceStopComm(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u"deviceStopComm() method called.")
        indigo.server.log(u"Stopping Enphase device: " + dev.name)
        dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Disabled")

    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    def checkForUpdates(self):
        if self.updater.checkForUpdate() == False:
            indigo.server.log(u"No Updates are Available")

    def updatePlugin(self):
        self.updater.update()

    def runConcurrentThread(self):

        try:
            x=0
            y=0
            while True:

                if self.debugLevel >= 2:
                    self.debugLog(u" ")

                for dev in indigo.devices.itervalues('self.EnphaseEnvoyDevice'):
                    if self.debugLevel >= 2:
                        self.debugLog(u"MainLoop:  {0}:".format(dev.name))

                    self.refreshDataForDev(dev)
                    self.sleep(1)
                    if x>=10 or x==0:
                        self.checkThePanels(dev)
                        self.sleep(2)
                        x=0
                    if y>5:
                        self.checkPanelInventory(dev)
                        self.sleep(5)
                        y=0
                x=x+1
                y=y+1
                self.sleep(15)

        except self.StopThread:
            self.debugLog(u'Restarting/or error. Stopping Enphase/Envoy thread.')
            pass

    def shutdown(self):
        if self.debugLevel >= 2:
            self.debugLog(u"shutdown() method called.")

    def startup(self):
        if self.debugLevel >= 2:
            self.debugLog(u"Starting Enphase Plugin. startup() method called.")

        # See if there is a plugin update and whether the user wants to be notified.
        try:
            if self.configUpdaterForceUpdate:
                self.updatePlugin()

            else:
                self.checkForUpdates()
            self.sleep(1)
        except Exception as error:
            self.errorLog(u"Update checker error: {0}".format(error))

    def validatePrefsConfigUi(self, valuesDict):
        if self.debugLevel >= 2:
            self.debugLog(u"validatePrefsConfigUi() method called.")

        error_msg_dict = indigo.Dict()

        # self.errorLog(u"Plugin configuration error: ")

        return True, valuesDict

    def getTheData(self, dev):
        """
        The getTheData() method is used to retrieve FrontView API Client Data
        """
        if self.debugLevel >= 2:
            self.debugLog(u"getTheData FrontViewAPI method called.")

                            # dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Download")
        try:
            url = 'http://' + dev.pluginProps['sourceXML'] + '/production.json'
            r = requests.get(url)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Result:" + unicode(result))

            dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")

            dev.setErrorStateOnServer(None)

            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + dev.name)
            self.WaitInterval = 60
            if self.debugLevel >= 2:
                self.debugLog(u"Device is offline. No data to return. ")
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('powerStatus', value = 'offline')
            dev.setErrorStateOnServer(u'Offline')
            result = ""
            return result

    def checkThePanels(self,dev):

        if self.debugLevel >= 2:
            self.debugLog(u'check thepanels called')
        if dev.pluginProps['activatePanels']:
            self.thePanels = self.getthePanels(dev)
            try:
                if self.thePanels is not None:
                    x = 1
                    update_time = t.strftime("%m/%d/%Y at %H:%M")
                    for dev in indigo.devices.itervalues('self.EnphasePanelDevice'):
                        deviceName = 'Enphase SolarPanel ' + str(x)
                        dev.updateStateOnServer('watts',value=int(self.thePanels[x-1]['lastReportWatts']))
                        dev.updateStateOnServer('serialNo', value=float(self.thePanels[x - 1]['serialNumber']))
                        dev.updateStateOnServer('maxWatts', value=int(self.thePanels[x - 1]['maxReportWatts']))
                        dev.updateStateOnServer('deviceLastUpdated', value=update_time)
                        dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
                        x = x + 1

            except Exception as error:
                self.errorLog('error within checkthePanels'+unicode(error.message))
                if self.debugLevel >= 2:
                    self.debugLog(u"Device is offline. No data to return. ")
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.setErrorStateOnServer(u'Offline')
                result = ""
                return result
        return

    def checkPanelInventory(self,dev):

        if self.debugLevel >= 2:
            self.debugLog(u"checkPanelInventory Enphase Panels method called.")

        if dev.pluginProps['activatePanels']:

            self.inventoryDict = self.getInventoryData(dev)

            try:
                if self.inventoryDict is not None:
                    for dev in indigo.devices.itervalues('self.EnphasePanelDevice'):
                        for devices in self.inventoryDict[0]['devices']:
                            #if self.debugLevel >=2:
                               # self.debugLog(u'checking serial numbers')
                               # self.errorLog(u'device serial:'+str(int(dev.states['serialNo'])))
                               # self.errorLog(u'panel serial no:'+str(devices['serial_num']))

                            if int(dev.states['serialNo']) == int(devices['serial_num']):
                                dev.updateStateOnServer('status',   value=str(devices['device_status']))
                                dev.updateStateOnServer('modelNo', value=str(devices['part_num']))
                                dev.updateStateOnServer('producing',   value=str(devices['producing']))
                                dev.updateStateOnServer('communicating', value=str(devices['communicating']))
                    return

            except Exception as error:
                self.errorLog('error within checkthePanels'+unicode(error.message))
                if self.debugLevel >= 2:
                    self.debugLog(u"Device is offline. No data to return. ")
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.setErrorStateOnServer(u'Offline')
                result = ""
                return result

        return


    def getInventoryData(self, dev):

        if self.debugLevel >= 2:
            self.debugLog(u"getInventoryData Enphase Panels method called.")
        try:
            url = 'http://' + dev.pluginProps['sourceXML'] + '/inventory.json'
            r = requests.get(url)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Inventory Result:" + unicode(result))
            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + dev.name)
            if self.debugLevel >= 2:
                self.debugLog(u"Device is offline. No data to return. ")
            # dev.updateStateOnServer('deviceTimestamp', value=t.time())
            result = ""
            return result


    def getthePanels(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u"getthePanels Enphase Envoy method called.")

        if dev.pluginProps['envoySerial'] is not None:

            try:
                url = 'http://' + dev.pluginProps['sourceXML'] + '/api/v1/production/inverters'
                password = dev.pluginProps['envoySerial']
                password = password[-6:]

                if self.debugLevel >=2:
                    self.debugLog(u"getthePanels: Password:"+unicode(password))

                r = requests.get(url, auth=HTTPDigestAuth('envoy',password))
                result = r.json()
                if self.debugLevel >= 2:
                    self.debugLog(u"Inverter Result:" + unicode(result))

                return result

            except Exception as error:

                indigo.server.log(u"Error connecting to Device:" + dev.name)

                if self.debugLevel >= 2:
                    self.debugLog(u"Device is offline. No data to return. ")

                # dev.updateStateOnServer('deviceTimestamp', value=t.time())
                for dev in indigo.devices.itervalues('self.EnphasePanelDevice'):
                    dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                    dev.updateStateOnServer('watts', value=0)
                    dev.setErrorStateOnServer(u'Offline')

                result = ""
                return result

    def parseStateValues(self, dev):
        """
        The parseStateValues() method walks through the dict and assigns the
        corresponding value to each device state.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"Saving Values method called.")

        try:
            dev.updateStateOnServer('numberInverters', value=int(self.finalDict['production'][0]['activeCount']))
            dev.updateStateOnServer('productionWattsNow', value=int(self.finalDict['production'][1]['wNow']))
            dev.updateStateOnServer('consumptionWattsNow', value=int(self.finalDict['consumption'][0]['wNow']))
            dev.updateStateOnServer('netConsumptionWattsNow', value=int(self.finalDict['consumption'][1]['wNow']))
            dev.updateStateOnServer('production7days', value=int(self.finalDict['production'][1]['whLastSevenDays']))
            dev.updateStateOnServer('consumption7days', value=int(self.finalDict['consumption'][0]['whLastSevenDays']))


            dev.updateStateOnServer('storageActiveCount', value=int(self.finalDict['storage'][0]['activeCount']))
            dev.updateStateOnServer('storageWattsNow', value=int(self.finalDict['storage'][0]['wNow']))
            dev.updateStateOnServer('storageState', value=self.finalDict['storage'][0]['state'])
            dev.updateStateOnServer('storagePercentFull', value=int(self.finalDict['storage'][0]['percentFull']))

            #dev.stateListOrDisplayStateIdChanged()
            update_time = t.strftime("%m/%d/%Y at %H:%M")
            dev.updateStateOnServer('deviceLastUpdated', value=update_time)
            reading_time = datetime.datetime.fromtimestamp(self.finalDict['production'][0]['readingTime'])
            #format_reading_time = t.strftime()
            dev.updateStateOnServer('readingTime', value=str(reading_time))
            timeDifference = int(t.time() - t.mktime(reading_time.timetuple()))
            dev.updateStateOnServer('secsSinceReading', value=timeDifference)

            if int(self.finalDict['production'][1]['wNow']) >= int(self.finalDict['consumption'][0]['wNow']) :
                #Generating more Power
                dev.updateStateOnServer('powerStatus', value = 'exporting', uiValue='Exporting Power')
                dev.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOff)
            else:
                #Must be opposite or offline
                dev.updateStateOnServer('powerStatus', value = 'importing', uiValue='Importing Power')
                dev.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOn)

        except Exception as error:
             if self.debugLevel >= 2:
                 self.errorLog(u"Saving Values errors:"+str(error.message))

    def setStatestonil(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u'setStates to nil run')

    def generatePanelDevices(self, valuesDict, typeId, devId):
        if self.debugLevel >= 2:
            self.debugLog(u'generate Panels run')
        try:
            #delete all panel devices first up
            for dev in indigo.devices.itervalues('self.EnphasePanelDevice'):
                indigo.device.delete(dev.id)
                if self.debugLevel >2:
                    self.debugLog(u'Deleting Device'+unicode(dev.id))

            dev = indigo.devices[devId]
            if self.debugLevel>=2:
                self.debugLog(u'Folder ID'+str(dev.folderId))
            self.thePanels = self.getthePanels(dev)
            if self.thePanels is not None:
                x = 1
                for array in self.thePanels:
                     deviceName = 'Enphase SolarPanel '+str(x)
                     device = indigo.device.create(address=deviceName, deviceTypeId='EnphasePanelDevice',name=deviceName,protocol=indigo.kProtocol.Plugin, folder=dev.folderId)
                     x=x+1
            #now fill with data
            self.sleep(2)
            self.checkThePanels(dev)


        except Exception as error:
            self.errorLog(u'error within generate panels'+unicode(error.message))

    def deletePanelDevices(self, valuesDict, typeId, devId):
        if self.debugLevel >= 2:
            self.debugLog(u'Delete Panels run')

        try:
            # delete all panel devices first up
            for dev in indigo.devices.itervalues('self.EnphasePanelDevice'):
                indigo.device.delete(dev.id)
                if self.debugLevel > 2:
                    self.debugLog(u'Deleting Device' + unicode(dev.id))
        except Exception as error:
            self.errorLog(u'error within delete panels' + unicode(error.message))

    def refreshDataAction(self, valuesDict):
        """
        The refreshDataAction() method refreshes data for all devices based on
        a plugin menu call.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"refreshDataAction() method called.")
        self.refreshData()
        return True

    def refreshData(self):
        """
        The refreshData() method controls the updating of all plugin
        devices.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"refreshData() method called.")

        try:
            # Check to see if there have been any devices created.
            if indigo.devices.itervalues(filter="self"):
                if self.debugLevel >= 2:
                    self.debugLog(u"Updating data...")

                for dev in indigo.devices.itervalues(filter="self"):
                    self.refreshDataForDev(dev)

            else:
                indigo.server.log(u"No Enphase Client devices have been created.")

            return True

        except Exception as error:
            self.errorLog(u"Error refreshing devices. Please check settings.")
            self.errorLog(unicode(error))
            return False

    def refreshDataForDev(self, dev):

        if dev.configured:
            if self.debugLevel >= 2:
                self.debugLog(u"Found configured device: {0}".format(dev.name))

            if dev.enabled:
                if self.debugLevel >= 2:
                    self.debugLog(u"   {0} is enabled.".format(dev.name))

                # timeDifference = int(t.time()) - int(dev.states['deviceTimestamp'])
                # Change to using Last Updated setting - removing need for deviceTimestamp altogether

                timeDifference = int(t.time() - t.mktime(dev.lastChanged.timetuple()))
                if self.debugLevel >= 1:
                    self.debugLog(dev.name + u": Time Since Device Update = " + unicode(timeDifference))
                    # self.errorLog(unicode(dev.lastChanged))
                # Get the data.

                # If device is offline wait for 60 seconds until rechecking
                if dev.states['deviceIsOnline'] == False and timeDifference >= 180:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Offline: Refreshing device: {0}".format(dev.name))
                    self.finalDict = self.getTheData(dev)

                # if device online normal time
                if dev.states['deviceIsOnline']:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Online: Refreshing device: {0}".format(dev.name))
                    self.finalDict = self.getTheData(dev)
                    #ignore panel level data until later
                    #self.PanelDict = self.getthePanels(dev)


                    # Put the final values into the device states - only if online
                if dev.states['deviceIsOnline']:
                    self.parseStateValues(dev)
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"    Disabled: {0}".format(dev.name))

    def refreshDataForDevAction(self, valuesDict):
        """
        The refreshDataForDevAction() method refreshes data for a selected device based on
        a plugin menu call.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"refreshDataForDevAction() method called.")

        dev = indigo.devices[valuesDict.deviceId]

        self.refreshDataForDev(dev)
        return True

    def stopSleep(self, start_sleep):
        """
        The stopSleep() method accounts for changes to the user upload interval
        preference. The plugin checks every 2 seconds to see if the sleep
        interval should be updated.
        """
        try:
            total_sleep = float(self.pluginPrefs.get('configMenuUploadInterval', 300))
        except:
            total_sleep = iTimer  # TODO: Note variable iTimer is an unresolved reference.
        if t.time() - start_sleep > total_sleep:
            return True
        return False

    def toggleDebugEnabled(self):
        """
        Toggle debug on/off.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"toggleDebugEnabled() method called.")
        if not self.debug:
            self.debug = True
            self.pluginPrefs['showDebugInfo'] = True
            indigo.server.log(u"Debugging on.")
            self.debugLog(u"Debug level: {0}".format(self.debugLevel))

        else:
            self.debug = False
            self.pluginPrefs['showDebugInfo'] = False
            indigo.server.log(u"Debugging off.")

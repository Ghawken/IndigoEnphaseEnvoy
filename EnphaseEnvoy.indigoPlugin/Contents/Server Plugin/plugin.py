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

        self.timeOutCount = 0
        self.debug = self.pluginPrefs.get('showDebugInfo', False)
        self.debugLevel = self.pluginPrefs.get('showDebugLevel', "1")
        self.deviceNeedsUpdated = ''
        self.prefServerTimeout = int(self.pluginPrefs.get('configMenuServerTimeout', "15"))
        self.updater = GitHubPluginUpdater(self)
        self.configUpdaterInterval = self.pluginPrefs.get('configUpdaterInterval', 24)
        self.configUpdaterForceUpdate = self.pluginPrefs.get('configUpdaterForceUpdate', False)
        self.debugupdate = self.pluginPrefs.get('debugupdate', False)
        self.openStore = self.pluginPrefs.get('openStore', False)

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
            self.debugupdate = valuesDict.get('debugupdate', False)
            self.openStore = valuesDict.get('openStore', False)

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


        #self.errorLog(unicode(dev.model))

        # CHECK IF PANEL - IF PANEL START OFFLINE
        # IF ENVOY START ONLINE
        if dev.model=='Enphase Panel':
            #self.errorLog(' Enphase Panel')
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            #dev.updateStateImageOnServer(indigo.kStateImageSel.Auto)
            dev.updateStateOnServer('watts', value=0)
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
            dev.stateListOrDisplayStateIdChanged()
            return
        #number_Panels = 0
        #numer_Panels = indigo.devices.len(filter='self.EnphasePanelDevice')
        indigo.server.log(u"Starting Enphase/Envoy device: " + dev.name )
        dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
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
        if dev.model == 'Enphase Envoy-S':
            dev.updateStateOnServer('powerStatus', value='offline', uiValue='Offline')
            dev.updateStateOnServer('generatingPower', value=False)
            dev.updateStateOnServer('numberInverters', value=0)
            dev.updateStateOnServer('productionWattsNow', value=0)
            dev.updateStateOnServer('consumptionWattsNow', value=0)
            dev.updateStateOnServer('netConsumptionWattsNow', value=0)
            dev.updateStateOnServer('production7days', value=0)
            dev.updateStateOnServer('consumption7days', value=0)
            dev.updateStateOnServer('consumptionWattsToday', value=0)
            dev.updateStateOnServer('productionWattsToday', value=0)
            dev.updateStateOnServer('storageActiveCount', value=0)
            dev.updateStateOnServer('storageWattsNow', value=0)
            dev.updateStateOnServer('storageState', value='Offline')
            dev.updateStateOnServer('storagePercentFull', value=0)
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
        if dev.model == 'Enphase Panel':
            dev.updateStateOnServer('watts', value=0)
            #dev.updateStateOnServer('serialNo', value=0)
            dev.updateStateOnServer('maxWatts', value=0)
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('status', value='')
            dev.updateStateOnServer('modelNo', value='')
            dev.updateStateOnServer('producing', value=False)
            dev.updateStateOnServer('communicating', value=False)
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
        if dev.model== 'Enphase Legacy':
            dev.updateStateOnServer('wattHoursLifetime', value=0)
            dev.updateStateOnServer('wattHoursSevenDays', value=0)
            dev.updateStateOnServer('wattHoursToday', value=0)
            dev.updateStateOnServer('wattsNow', value=0)

    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    def checkForUpdates(self):

        updateavailable = self.updater.getLatestVersion()
        if updateavailable and self.openStore:
            self.logger.info(u'Enphase Plugin: Update Checking.  Update is Available.  Taking you to plugin Store. ')
            self.sleep(2)
            self.pluginstoreUpdate()
        elif updateavailable and not self.openStore:
            self.errorLog(u'Enphase Plugin: Update Checking.  Update is Available.  Please check Store for details/download.')
    def updatePlugin(self):
        self.updater.update()

    def pluginstoreUpdate(self):
        iurl = 'http://www.indigodomo.com/pluginstore/105/'
        self.browserOpen(iurl)

    def refreshDatafromMenu(self):
        indigo.server.log(u'Manually Refreshing Enphase Data:')
        for dev in indigo.devices.itervalues('self.EnphaseEnvoyDevice'):
            if self.debugLevel >= 2:
                self.debugLog(u'Quick Checks Before Loop')
            if dev.enabled:
                self.refreshDataForDev(dev)
                self.sleep(30)
                self.checkPanelInventory(dev)
                self.sleep(30)
                self.checkThePanels(dev)
                self.sleep(10)
        return


    def runConcurrentThread(self):

        try:
            x=0
            y=0
            #One quick check on startup - to avoid Panel delays

            for dev in indigo.devices.itervalues('self.EnphaseEnvoyDevice'):
                if self.debugLevel>=2:
                    self.debugLog(u'Quick Checks Before Loop')
                if dev.enabled:
                    self.refreshDataForDev(dev)
                    self.sleep(30)
                    self.checkPanelInventory(dev)
                    self.sleep(30)
                    self.checkThePanels(dev)
                    self.sleep(10)


            while True:

                if self.debugLevel >= 2:
                    self.debugLog(u" ")

                for dev in indigo.devices.itervalues('self.EnphaseEnvoyDevice'):
                    if self.debugLevel >= 2:
                        self.debugLog(u"MainLoop:  {0}:".format(dev.name))
                    if dev.enabled:
                        self.refreshDataForDev(dev)
                        self.sleep(1)
                        if x>=5:
                            self.checkThePanels(dev)
                            self.sleep(5)
                            x=0
                        if y>=8:
                            self.checkPanelInventory(dev)
                            self.sleep(5)
                            y=0
                for dev in indigo.devices.itervalues('self.EnphaseEnvoyLegacy'):
                    if self.debugLevel >=2:
                        self.debugLog(u'Checking Legacy devices: {0}:'.format(dev.name))
                    if dev.enabled:
                        self.legacyRefreshEnvoy(dev)

                x=x+1
                y=y+1
                self.sleep(60)

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
        The getTheData() method is used to retrieve  API Client Data
        """
        if self.debugLevel >= 2:
            self.debugLog(u"getTheData PRODUCTION METHOD method called.")


        try:
            url = 'http://' + dev.pluginProps['sourceXML'] + '/production.json'
            r = requests.get(url,timeout=4)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Result:" + str(result))

            dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")

            dev.setErrorStateOnServer(None)

            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + unicode(dev.name) +" Error is:"+unicode(error.message))
            self.WaitInterval = 60
            if self.debugLevel >= 2:
                self.debugLog(u"Device is offline. No data to return. ")
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('powerStatus', value = 'offline')
            dev.setErrorStateOnServer(u'Offline')
            result = None
            return result

    def legacyGetTheData(self, dev):
        """
        The getTheData() method is used to retrieve  API Client Data
        """
        if self.debugLevel >= 2:
            self.debugLog(u"getTheData PRODUCTION METHOD method called.")


        try:
            url = 'http://' + dev.pluginProps['sourceXML'] + '/api/v1/production'
            r = requests.get(url,timeout=4)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Result:" + str(result))

            dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")

            dev.setErrorStateOnServer(None)

            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + unicode(dev.name) +"Error is:"+unicode(error.message))
            self.WaitInterval = 60
            if self.debugLevel >= 2:
                self.debugLog(u"Device is offline. No data to return. ")
            dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
            dev.updateStateOnServer('powerStatus', value = 'offline')
            dev.setErrorStateOnServer(u'Offline')
            result = None
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
                        if dev.states['producing']:
                            dev.updateStateOnServer('watts',value=int(self.thePanels[x-1]['lastReportWatts']),uiValue=str(self.thePanels[x-1]['lastReportWatts']))

                        dev.updateStateOnServer('lastCommunication', value=str(datetime.datetime.fromtimestamp( int(self.thePanels[x-1]['lastReportDate'])).strftime('%c')))
                        dev.updateStateOnServer('serialNo', value=float(self.thePanels[x - 1]['serialNumber']))
                        dev.updateStateOnServer('maxWatts', value=int(self.thePanels[x - 1]['maxReportWatts']))
                        dev.updateStateOnServer('deviceLastUpdated', value=update_time)
                        dev.updateStateOnServer('deviceIsOnline', value=True, uiValue="Online")
                        dev.setErrorStateOnServer(None)
                        x = x + 1

            except Exception as error:
                self.errorLog('error within checkthePanels:'+unicode(error))
                if self.debugLevel >= 2:
                    self.debugLog(u"Device is offline. No data to return. ")
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.setErrorStateOnServer(u'Offline')
                result = None
                return result
        return

    def checkPanelInventory(self,dev):
        if self.debugLevel >= 2:
            self.debugLog(u"checkPanelInventory Enphase Panels method called.")

        if dev.pluginProps['activatePanels'] and dev.states['deviceIsOnline']:
            self.inventoryDict = self.getInventoryData(dev)
            try:
                if self.inventoryDict is not None:
                    for dev in indigo.devices.itervalues('self.EnphasePanelDevice'):
                        for devices in self.inventoryDict[0]['devices']:
                            #if self.debugLevel >=2:
                               # self.debugLog(u'checking serial numbers')
                               # self.errorLog(u'device serial:'+str(int(dev.states['serialNo'])))
                               # self.errorLog(u'panel serial no:'+str(devices['serial_num']))
                            #self.errorLog(u'Dev.states Producing type is' + str(type(dev.states['producing'])))
                            #self.errorLog(u'Devices Producing type is' + str(type(devices['producing'])))
                            if int(dev.states['serialNo']) == int(devices['serial_num']):
                                if dev.states['producing']==True and devices['producing']==False:
                                    if self.debugLevel >= 1:
                                        self.debugLog(u'Producing: States true, devices(producing) False: devices[prodcing] equals:'+str(devices['producing']))
                                    #  change only once
                                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                                    dev.updateStateOnServer('watts', value=0, uiValue='--')
                                if dev.states['producing'] == False and devices['producing'] == True:
                                    if self.debugLevel >= 1:
                                        self.debugLog(u'States Producing False, and devices now shows True: device(producing):' + str(devices['producing']))
                                    dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                                    dev.updateStateOnServer('watts', value=dev.states['watts'], uiValue=str(dev.states['watts']))
                                dev.updateStateOnServer('status',   value=str(devices['device_status']))
                                dev.updateStateOnServer('modelNo', value=str(devices['part_num']))
                                dev.updateStateOnServer('producing',   value=devices['producing'])
                                dev.updateStateOnServer('communicating', value=devices['communicating'])


                    return

            except Exception as error:
                self.errorLog('error within checkPanelInventory:'+unicode(error))
                if self.debugLevel >= 2:
                    self.debugLog(u"Device is offline. No data to return. ")
                dev.updateStateOnServer('deviceIsOnline', value=False, uiValue="Offline")
                dev.setErrorStateOnServer(u'Offline')
                result = None
                return result

        return


    def getInventoryData(self, dev):

        if self.debugLevel >= 2:
            self.debugLog(u"getInventoryData Enphase Panels method called.")
        try:
            url = 'http://' + dev.pluginProps['sourceXML'] + '/inventory.json'
            r = requests.get(url, timeout =5)
            result = r.json()
            if self.debugLevel >= 2:
                self.debugLog(u"Inventory Result:" + unicode(result))
            return result

        except Exception as error:

            indigo.server.log(u"Error connecting to Device:" + dev.name)
            if self.debugLevel >= 2:
                self.debugLog(u"Device is offline. No data to return. ")
            # dev.updateStateOnServer('deviceTimestamp', value=t.time())
            result = None
            return result


    def getthePanels(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u"getthePanels Enphase Envoy method called.")

        if dev.pluginProps['envoySerial'] is not None and dev.states['deviceIsOnline']:

            try:
                url = 'http://' + dev.pluginProps['sourceXML'] + '/api/v1/production/inverters'
                password = dev.pluginProps['envoySerial']
                password = password[-6:]

                if self.debugLevel >=2:
                    self.debugLog(u"getthePanels: Password:"+unicode(password))

                r = requests.get(url, auth=HTTPDigestAuth('envoy',password), timeout=2)
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

                result = None
                return result

    def legacyParseStateValues(self, dev):
        """
        The parseStateValues() method walks through the dict and assigns the
        corresponding value to each device state.
        """
        if self.debugLevel >= 2:
            self.debugLog(u"Saving Values method called.")

        try:
            dev.updateStateOnServer('wattHoursLifetime', value=int(self.finalDict['wattHoursLifetime']))
            dev.updateStateOnServer('wattHoursSevenDays', value=int(self.finalDict['wattHoursSevenDays']))
            dev.updateStateOnServer('wattHoursToday', value=int(self.finalDict['wattHoursToday']))
            dev.updateStateOnServer('wattsNow', value=int(self.finalDict['wattsNow']))
            if self.debugLevel >= 1:
                self.debugLog("State Image Selector:"+str(dev.displayStateImageSel))




        except Exception as error:
             if self.debugLevel >= 2:
                 self.errorLog(u"Saving Values errors:"+str(error.message))


    def parseStateValues(self, dev):
        """
        The parseStateValues() method walks through the dict and assigns the
        corresponding value to each device state.
        """

        #testdata2 = {u'production': [{u'activeCount': 43, u'wNow': 1912, u'readingTime': 1493848912, u'type': u'inverters',u'whLifetime': 9422470.6777777784},
        #                 {u'whToday': 51894.915000000001, u'pwrFactor': 0.93000000000000005, u'readingTime': 1493848913,u'activeCount': 1, u'rmsVoltage': 250.69399999999999, u'reactPwr': 541.96500000000003,
        #                  u'whLifetime': 9352075.9149999991, u'apprntPwr': 1916.5229999999999,u'wNow': 1778.6320000000001, u'type': u'eim', u'whLastSevenDays': 326631.91499999998,
         #                 u'rmsCurrent': 15.289999999999999}], u'consumption': [{u'varhLagLifetime': 0, u'rmsVoltage': 0, u'pwrFactor': 0, u'whToday': 0, u'vahToday': 0,
        #     u'varhLeadLifetime': 0, u'varhLeadToday': 0, u'activeCount': 0, u'varhLagToday': 0, u'vahLifetime': 0,u'reactPwr': 0, u'whLifetime': 0, u'apprntPwr': 0, u'wNow': 0, u'type': u'eim', u'whLastSevenDays': 0,
        #     u'rmsCurrent': 0}]}

        #self.finalDict = testdata2

        #testdata = {u'production': [{u'activeCount': 32, u'wNow': 303, u'readingTime': 1484494980, u'type': u'inverters', u'whLifetime': 1799748.9794444444}, {u'whToday': 137.262, u'pwrFactor': 0.53, u'readingTime': 1484494980, u'activeCount': 1, u'rmsVoltage': 248.215, u'reactPwr': 490.766, u'whLifetime': 1321326.262, u'apprntPwr': 596.966, u'wNow': 316.044, u'type': u'eim', u'whLastSevenDays': 116064.262, u'rmsCurrent': 4.81}], u'consumption': [{u'varhLagLifetime': 913691.045, u'rmsVoltage': 248.132, u'pwrFactor': 0.35, u'whToday': 6075.567, u'vahToday': 8331.054, u'varhLeadLifetime': 912659.572, u'varhLeadToday': 4580.572, u'readingTime': 1484494980, u'activeCount': 1, u'varhLagToday': 4093.045, u'vahLifetime': 2530344.054, u'reactPwr': 402.82, u'whLifetime': 1756854.567, u'apprntPwr': 3780.981, u'wNow': 1337.481, u'type': u'eim', u'whLastSevenDays': 161357.567, u'rmsCurrent': 15.238}]}
        #self.finalDict = testdata



        if self.debugLevel >= 2:
            self.debugLog(u"Saving Values method called.")
            self.debugLog(unicode(self.finalDict))

        try:
            consumptionWatts =0
            productionWatts =0
            check = "production" in self.finalDict
            # Check that finalDict contains a production list
            if check:
                dev.updateStateOnServer('numberInverters', value=int(self.finalDict['production'][0]['activeCount']))
                if len(self.finalDict['production'])>1:
                    dev.updateStateOnServer('productionWattsNow', value=int(self.finalDict['production'][1]['wNow']))
                    productionWatts = int(self.finalDict['production'][1]['wNow'])
                    dev.updateStateOnServer('production7days', value=int(self.finalDict['production'][1]['whLastSevenDays']))
                    dev.updateStateOnServer('productionWattsToday', value=int(self.finalDict['production'][1]['whToday']))
                else:
                    if self.debugLevel >= 2:
                        self.debugLog(u"no Production 2 result found.")
                    dev.updateStateOnServer('productionWattsNow', value=0)
                    dev.updateStateOnServer('production7days',value=0)
                    dev.updateStateOnServer('productionWattsToday',value=0)
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"no Production result found.")
                dev.updateStateOnServer('numberInverters', value=0)

            check = "consumption" in self.finalDict

            if check:
                dev.updateStateOnServer('consumptionWattsNow', value=int(self.finalDict['consumption'][0]['wNow']))
                consumptionWatts = int(self.finalDict['consumption'][0]['wNow'])
                dev.updateStateOnServer('consumption7days', value=int(self.finalDict['consumption'][0]['whLastSevenDays']))
                dev.updateStateOnServer('consumptionWattsToday', value=int(self.finalDict['consumption'][0]['whToday']))
                if len(self.finalDict['consumption'])>1:
                    dev.updateStateOnServer('netConsumptionWattsNow', value=int(self.finalDict['consumption'][1]['wNow']))
                else:
                    if self.debugLevel >=2:
                        self.debugLog(u'No netConsumption being reporting.....Calculating....')
                    # Calculate?
                    #
                    netConsumption = int(self.finalDict['consumption'][0]['wNow']) - int(self.finalDict['production'][1]['wNow'])
                    dev.updateStateOnServer('netConsumptionWattsNow', value=int(netConsumption))
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"no Consumption result found.")

            check = "storage" in self.finalDict
            if check:
                dev.updateStateOnServer('storageActiveCount', value=int(self.finalDict['storage'][0]['activeCount']))
                dev.updateStateOnServer('storageWattsNow', value=int(self.finalDict['storage'][0]['wNow']))
                dev.updateStateOnServer('storageState', value=self.finalDict['storage'][0]['state'])
                #dev.updateStateOnServer('storagePercentFull', value=int(self.finalDict['storage'][0]['percentFull']))
            else:
                if self.debugLevel >= 2:
                    self.debugLog(u"no Storage result found.")
                dev.updateStateOnServer('storageState', value='No Data')

            update_time = t.strftime("%m/%d/%Y at %H:%M")
            dev.updateStateOnServer('deviceLastUpdated', value=update_time)
            reading_time = datetime.datetime.fromtimestamp(self.finalDict['production'][1]['readingTime'])
            #format_reading_time = t.strftime()
            dev.updateStateOnServer('readingTime', value=str(reading_time))
            timeDifference = int(t.time() - t.mktime(reading_time.timetuple()))
            dev.updateStateOnServer('secsSinceReading', value=timeDifference)
            if self.debugLevel >= 1:
                self.debugLog("State Image Selector:"+str(dev.displayStateImageSel))

            if productionWatts >= consumptionWatts and (dev.states['powerStatus']=='importing' or dev.states['powerStatus']=='offline'):
                #Generating more Power - and a change
                # If Generating Power - but device believes importing - recent change unpdate to refleect
                if self.debugLevel >= 2:
                    self.debugLog(u'**CHANGED**: Exporting Power')

                dev.updateStateOnServer('powerStatus', value = 'exporting', uiValue='Exporting Power')
                dev.updateStateOnServer('generatingPower', value=True)
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                if self.debugLevel >= 1:
                    self.debugLog("State Image Selector:" + str(dev.displayStateImageSel))

            if productionWatts < consumptionWatts and (dev.states['powerStatus'] == 'exporting' or dev.states['powerStatus']=='offline'):
                #Must be opposite or and again a change only
                if self.debugLevel >= 2:
                    self.debugLog(u'**CHANGED**: Importing power')

                dev.updateStateOnServer('powerStatus', value='importing', uiValue='Importing Power')
                dev.updateStateOnServer('generatingPower', value=False)
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
                if self.debugLevel >= 1:
                    self.debugLog("State Image Selector:" + str(dev.displayStateImageSel))
        # add Cost check device here

            for costdev in indigo.devices.itervalues('self.EnphaseEnvoyCostDevice'):
                if self.debugLevel >2:
                    self.debugLog(u'Updating Cost Device')
                self.updateCostDevice(dev, costdev)

        except Exception as error:
             if self.debugLevel >= 2:
                 self.errorLog(u"Saving Values errors:"+str(error.message))

    def updateCostDevice(self, dev, costdev):
        if self.debugLevel>=2:
            self.debugLog(u'updateCostDevice Run')
        # get current Tarrif
        try:
            tariffkwh = float(costdev.pluginProps['envoyTariffkWh'])
        except Exception as error:
            if self.debugLevel>=2:
                self.debugLog(u'error with Tarriff kwh using 1.0:' +error.message   )
            tariffkwh = 1.0


        productionTarrifToday = float(dev.states['productionWattsToday']/1000 )
        costdev.updateStateOnServer('productionTarrifToday', value='${:,.2f}'.format(productionTarrifToday * tariffkwh))
        costdev.updateStateOnServer('productionkWToday',value=float(dev.states['productionWattsToday']))

        consumptionTarrifToday = float(dev.states['consumptionWattsToday']/1000 )
        costdev.updateStateOnServer('consumptionTarrifToday', value='${:,.2f}'.format(consumptionTarrifToday * tariffkwh))
        costdev.updateStateOnServer('consumptionkWToday', value=float(dev.states['consumptionWattsToday']))

        productionTarrif7days = float(dev.states['production7days']/1000 )
        costdev.updateStateOnServer('productionTarrif7days', value='${:,.2f}'.format(productionTarrif7days * tariffkwh))
        costdev.updateStateOnServer('productionkW7days', value=float(dev.states['production7days']))

        consumptionTarrif7days = float(dev.states['consumption7days']/1000 )
        costdev.updateStateOnServer('consumptionTarrif7days', value='${:,.2f}'.format(consumptionTarrif7days * tariffkwh))
        costdev.updateStateOnServer('consumptionkW7days', value=float(dev.states['consumption7days']/1000))

        netTarrif7days = float (productionTarrif7days - consumptionTarrif7days)
        netTarrifToday = float (productionTarrifToday - consumptionTarrifToday)
        costdev.updateStateOnServer('netTarrifToday',                    value='${:,.2f}'.format(netTarrifToday * tariffkwh))
        costdev.updateStateOnServer('netTarrif7days', value='${:,.2f}'.format(netTarrif7days * tariffkwh))


        update_time = t.strftime("%m/%d/%Y at %H:%M")
        costdev.updateStateOnServer('deviceLastUpdated', value=update_time)

        return


    def setStatestonil(self, dev):
        if self.debugLevel >= 2:
            self.debugLog(u'setStates to nil run')

    def generatePanelDevices(self, valuesDict, typeId, devId):
        if self.debugLevel >= 2:
            self.debugLog(u'generate Panels run')
        try:
            #delete all panel devices first up

            dev = indigo.devices[devId]

            if self.debugLevel>=2:
                self.debugLog(u'Folder ID'+str(dev.folderId))
            self.thePanels = self.getthePanels(dev)
            if self.thePanels is not None:
                x = 1
                for array in self.thePanels:
                     deviceName = 'Enphase SolarPanel '+str(x)
                     noDevice = True
                     for panels in indigo.devices.itervalues('self.EnphasePanelDevice'):
                         if panels.name == deviceName:
                            noDevice = False
                     if noDevice:
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
            self.errorLog(unicode(error.message))
            return False

    def refreshDataForDev(self, dev):

        if dev.configured:
            if self.debugLevel >= 2:
                self.debugLog(u"Found configured device: {0}".format(dev.name))

            if dev.enabled:
                if self.debugLevel >= 2:
                    self.debugLog(u"   {0} is enabled.".format(dev.name))
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

    def legacyRefreshEnvoy(self,dev):
        if dev.configured:
            if self.debugLevel >= 2:
                self.debugLog(u"Found configured device: {0}".format(dev.name))

            if dev.enabled:
                if self.debugLevel >= 2:
                    self.debugLog(u"   {0} is enabled.".format(dev.name))
                timeDifference = int(t.time() - t.mktime(dev.lastChanged.timetuple()))
                if self.debugLevel >= 1:
                    self.debugLog(dev.name + u": Time Since Device Update = " + unicode(timeDifference))
                    # self.errorLog(unicode(dev.lastChanged))
                # Get the data.
                # If device is offline wait for 60 seconds until rechecking
                if dev.states['deviceIsOnline'] == False and timeDifference >= 180:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Offline: Refreshing device: {0}".format(dev.name))

                    self.finalDict = self.LegacyGetTheData(dev)
                # if device online normal time

                if dev.states['deviceIsOnline']:
                    if self.debugLevel >= 2:
                        self.debugLog(u"Online: Refreshing device: {0}".format(dev.name))
                    self.finalDict = self.legacyGetTheData(dev)
                    #ignore panel level data until later
                    #self.PanelDict = self.getthePanels(dev)
                    # Put the final values into the device states - only if online
                if dev.states['deviceIsOnline']:
                    self.legacyParseStateValues(dev)
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

from enum import Enum

class GoogleApps(str, Enum): 
    GMAIL = 'gmail'
    DRIVE = 'drive'

class SupportedApps(str, Enum): 
    GMAIL = 'gmail'
    GOOGLE_DRIVE = 'drive'
    BROWSER = 'browser'

# This is the bcfg2 support for solaris
'''This provides (vestigal) bcfg2 support for Solaris'''
__revision__ = '$Revision$'

from Bcfg2.Client.Toolset import Toolset

def Detect():
    # until the code works
    return False

class Solaris(Toolset):
    '''This class implelements support for SYSV packages and standard /etc/init.d services'''

    def VerifyService(self, entry):
        return False

    def VerifyPackage(self, entry):
        return False

    def InstallService(self, entry):
        return False

    def InstallPackage(self, entry):
        return False



'''This is the bcfg2 support for apt-get'''
__revision__ = '$Revision$'

# suppress apt API warnings
import warnings
warnings.filterwarnings("ignore", "apt API not stable yet",
                        FutureWarning)
warnings.filterwarnings("ignore", "Accessed deprecated property Package.installedVersion, please see the Version class for alternatives.", DeprecationWarning)
warnings.filterwarnings("ignore", "Accessed deprecated property Package.candidateVersion, please see the Version class for alternatives.", DeprecationWarning)
import apt.cache
import os

import Bcfg2.Client.Tools
import Bcfg2.Options

# Options for tool locations
opts = {'install_path': Bcfg2.Options.CLIENT_APT_TOOLS_INSTALL_PATH,
        'var_path': Bcfg2.Options.CLIENT_APT_TOOLS_VAR_PATH,
        'etc_path': Bcfg2.Options.CLIENT_SYSTEM_ETC_PATH}
setup = Bcfg2.Options.OptionParser(opts)
setup.parse([])
install_path = setup['install_path']
var_path = setup['var_path']
etc_path = setup['etc_path']
DEBSUMS = '%s/bin/debsums' % install_path
APTGET = '%s/bin/apt-get' % install_path
DPKG = '%s/bin/dpkg' % install_path

class APT(Bcfg2.Client.Tools.Tool):
    '''The Debian toolset implements package and service operations and inherits
    the rest from Toolset.Toolset'''
    name = 'APT'
    __execs__ = [DEBSUMS, APTGET, DPKG]
    __important__ = ["%s/apt/sources.list" % etc_path,
                     "%s/cache/debconf/config.dat" % var_path,
                     "%s/cache/debconf/templates.dat" % var_path,
                     '/etc/passwd', '/etc/group',
                     '%s/apt/apt.conf' % etc_path,
                     '%s/dpkg/dpkg.cfg' % etc_path]
    __handles__ = [('Package', 'deb')]
    __req__ = {'Package': ['name', 'version']}
    pkgcmd = '%s ' % APTGET + \
             '-o DPkg::Options::=--force-overwrite ' + \
             '-o DPkg::Options::=--force-confold ' + \
             '--reinstall ' + \
             '-q=2 ' + \
             '--force-yes ' + \
             '-y install %s'

    def __init__(self, logger, cfg, setup):
        Bcfg2.Client.Tools.Tool.__init__(self, logger, cfg, setup)
        self.cfg = cfg
        os.environ["DEBIAN_FRONTEND"] = 'noninteractive'
        self.actions = {}
        if self.setup['kevlar'] and not self.setup['dryrun']:
            self.cmd.run("%s --force-confold --configure --pending" % DPKG)
            self.cmd.run("%s clean" % APTGET)
            self.pkg_cache = apt.cache.Cache()
            self.pkg_cache.update()
        self.pkg_cache = apt.cache.Cache()

    def FindExtra(self):
        '''Find extra packages'''
        packages = [entry.get('name') for entry in self.getSupportedEntries()]
        extras = [(p.name, p.installedVersion) for p in self.pkg_cache
                  if p.isInstalled and p.name not in packages]
        return [Bcfg2.Client.XML.Element('Package', name=name, \
                                         type='deb', version=version) \
                                         for (name, version) in extras]

    def VerifyDebsums(self, entry, modlist):
        output = self.cmd.run("%s -as %s" % (DEBSUMS, entry.get('name')))[1]
        if len(output) == 1 and "no md5sums for" in output[0]:
            self.logger.info("Package %s has no md5sums. Cannot verify" % \
                             entry.get('name'))
            entry.set('qtext', "Reinstall Package %s-%s to setup md5sums? (y/N) " \
                      % (entry.get('name'), entry.get('version')))
            return False
        files = []
        for item in output:
            if "checksum mismatch" in item:
                files.append(item.split()[-1])
            elif "changed file" in item:
                files.append(item.split()[3])
            elif "can't open" in item:
                files.append(item.split()[5])
            elif "is not installed" in item or "missing file" in item:
                self.logger.error("Package %s is not fully installed" \
                                  % entry.get('name'))
            else:
                self.logger.error("Got Unsupported pattern %s from debsums" \
                                  % item)
                files.append(item)
        # We check if there is file in the checksum to do
        if files:
            # if files are found there we try to be sure our modlist is sane
            # with erroneous symlinks
            modlist = [os.path.realpath(filename) for filename in modlist]
            bad = [filename for filename in files if filename not in modlist]
            if bad:
                self.logger.info("Package %s failed validation. Bad files are:" % \
                                 entry.get('name'))
                self.logger.info(bad)
                entry.set('qtext',
                          "Reinstall Package %s-%s to fix failing files? (y/N) " % \
                          (entry.get('name'), entry.get('version')))
                return False
        return True

    def VerifyPackage(self, entry, modlist, checksums=True):
        '''Verify package for entry'''
        if not 'version' in entry.attrib:
            self.logger.info("Cannot verify unversioned package %s" %
                             (entry.attrib['name']))
            return False
        pkgname = entry.get('name')
        if pkgname not in self.pkg_cache \
               or not self.pkg_cache[pkgname].isInstalled:
            self.logger.info("Package %s not installed" % (entry.get('name')))
            entry.set('current_exists', 'false')
            return False

        pkg = self.pkg_cache[pkgname]
        if entry.get('version') == 'auto':
            if self.pkg_cache._depcache.IsUpgradable(pkg._pkg):
                desiredVersion = pkg.candidateVersion
            else:
                desiredVersion = pkg.installedVersion
        elif entry.get('version') == 'any':
            desiredVersion = pkg.installedVersion
        else:
            desiredVersion = entry.get('version')
        if desiredVersion != pkg.installedVersion:
            entry.set('current_version', pkg.installedVersion)
            entry.set('qtext', "Modify Package %s (%s -> %s)? (y/N) " % \
                      (entry.get('name'), entry.get('current_version'),
                       desiredVersion))
            return False
        else:
            # version matches
            if not self.setup['quick'] and entry.get('verify', 'true') == 'true' \
                   and checksums:
                pkgsums = self.VerifyDebsums(entry, modlist)
                return pkgsums
            return True

    def Remove(self, packages):
        '''Deal with extra configuration detected'''
        pkgnames = " ".join([pkg.get('name') for pkg in packages])
        self.pkg_cache = apt.cache.Cache()
        if len(packages) > 0:
            self.logger.info('Removing packages:')
            self.logger.info(pkgnames)
            for pkg in pkgnames.split(" "):
                try:
                    self.pkg_cache[pkg].markDelete(purge=True)
                except:
                    self.pkg_cache[pkg].markDelete()
            try:
                self.pkg_cache.commit()
            except SystemExit:
                # thank you python-apt 0.6
                pass
            self.pkg_cache = apt.cache.Cache()
            self.modified += packages
            self.extra = self.FindExtra()

    def Install(self, packages, states):
        # it looks like you can't install arbitrary versions of software
        # out of the pkg cache, we will still need to call apt-get
        ipkgs = []
        bad_pkgs = []
        for pkg in packages:
            if pkg.get('name') not in self.pkg_cache:
                self.logger.error("APT has no information about package %s" % (pkg.get('name')))
                continue
            if pkg.get('version') in ['auto', 'any']:
                ipkgs.append("%s=%s" % (pkg.get('name'),
                                        self.pkg_cache[pkg.get('name')].candidateVersion))
                continue
            avail_vers = [x.VerStr for x in \
                          self.pkg_cache[pkg.get('name')]._pkg.VersionList]
            if pkg.get('version') in avail_vers:
                ipkgs.append("%s=%s" % (pkg.get('name'), pkg.get('version')))
                continue
            else:
                self.logger.error("Package %s: desired version %s not in %s" \
                                  % (pkg.get('name'), pkg.get('version'),
                                     avail_vers))
            bad_pkgs.append(pkg.get('name'))
        if bad_pkgs:
            self.logger.error("Cannot find correct versions of packages:")
            self.logger.error(bad_pkgs)
        if not ipkgs:
            return
        rc = self.cmd.run(self.pkgcmd % (" ".join(ipkgs)))[0]
        if rc:
            self.logger.error("APT command failed")
        self.pkg_cache = apt.cache.Cache()
        self.extra = self.FindExtra()
        for package in packages:
            states[package] = self.VerifyPackage(package, [], checksums=False)
            if states[package]:
                self.modified.append(package)

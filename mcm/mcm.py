#!/usr/bin/python3
import argparse
import xdg
import os
import pathlib
import logging
import urllib.request
import toml, json, jsonschema
import sys
import shutil
from urllib.parse import urlparse
import subprocess
import io
import re
import importlib.resources as pkg_resources
from . import static

try:
    import git
except ImportError:
   USING_GITPYTHON = False
else:
    # Ensure git is installed
    if shutil.which('git') is None:
        raise Exception('gitpython installed but git not installed')
    USING_GITPYTHON = True

try:
    import tarfile
except ImportError:
    USING_TARFILE = False
else:
    USING_TARFILE = True 
if shutil.which('scm') is None:
    raise Exception('scm is not installed')

class Mcm():
    def __init__(self, mcm_dir=None, target_dir=None, hostname=None, tags=None, config_schema_path='meta_package_config_schema.json', cache_dir=None):
        if mcm_dir is None:
            mcm_dir = os.path.join(xdg.XDG_DATA_HOME, 'mcm2')
        if cache_dir is None:
            cache_dir = os.path.join(xdg.XDG_CACHE_HOME, 'mcm')
        if target_dir is None:
            target_dir = target_dir=pathlib.Path.home()
        if tags is None:
            tags = []

        self.mcm_dir = pathlib.Path(mcm_dir)
        self.mcm_package_configs_dir = pathlib.Path(os.path.join(mcm_dir, 'configs'))
        self.mcm_package_packages_dir = pathlib.Path(os.path.join(mcm_dir, 'packages'))
        self.mcm_cache_dir = pathlib.Path(cache_dir)
        self.target_dir = target_dir
        self.hostname = hostname
        self.tags = tags

        # Create mcm dirs if does not exist
        self.mcm_package_configs_dir.mkdir(parents=True, exist_ok=True)
        self.mcm_package_packages_dir.mkdir(parents=True, exist_ok=True)
        self.mcm_cache_dir.mkdir(parents=True, exist_ok=True)

        # Create the cache file if it does not exist
        self.mcm_cache_file = os.path.join(cache_dir, 'cache.json')
        cache = {}
        if not os.path.exists(self.mcm_cache_file):
            with open(self.mcm_cache_file, 'w') as f:
                json.dump(cache, f)

        # Load meta-package config schema
        #with open(config_schema_path, 'r') as f:
        with pkg_resources.open_text(static, config_schema_path) as f:
            self.meta_package_config_schema = json.load(f)
        jsonschema.Draft7Validator.check_schema(self.meta_package_config_schema)

        self.package_statuses = ['notloaded', 'loaded', 'midinstall', 'midremove', 'installed']

    def _find_meta_package_by_name(self, meta_package_name):
        for file_name in os.listdir(self.mcm_package_configs_dir):
            file_dir = os.path.abspath(os.path.join(self.mcm_package_configs_dir, file_name))
            if toml.load(file_dir)['name'] == meta_package_name:
                return file_dir
        return None
    
    def _get_meta_package_by_name(self, meta_package_name):
        for file_name in os.listdir(self.mcm_package_configs_dir):
            file_dir = os.path.abspath(os.path.join(self.mcm_package_configs_dir, file_name))
            t = toml.load(file_dir)
            if t['name'] == meta_package_name:
                return t
        return None

    #               'package-name': {
    #                   'status': 'installed',
    #                   'path': '/package/path',
    #                   ...
    # Statuses: ['notloaded', 'loaded', 'midinstall', 'installed', 'midremove']
    def _get_package_cache(self, meta_package_name, package_name):
        joined_package_name = meta_package_name + '.' + package_name
        package_dir = os.path.join(self.mcm_package_packages_dir, joined_package_name)

        if not os.path.isdir(package_dir):
            return {'status': 'notloaded' }

        else:
            with open(self.mcm_cache_file, 'r') as f:
                try:
                    cache = json.load(f)
                except json.decoder.JSONDecodeError as e:
                    raise Exception('Cache file seriously broken.  Run mcm cache-fix to repair.')

            try:
                package_cache = cache[meta_package_name]['packages'][package_name]
                status = package_cache['status']
            except KeyError as e:
                raise Exception('Can\'t determine the status of package {}.{} - cache has been tampered with.  Run mcm cache-fix to repair.'.format(meta_package_name, package_name))
            else:
                if status not in self.package_statuses:
                    raise Exception('Invalid package status {} for package {}.{} - cache has been tampered with.  Run mcm cache-fix to repair.'.format(status, meta_package_name, package_name))
                return package_cache

    def _invoke_scm_install(self, meta_package_name, package_name, target_dir=None, get_attributes_from_cache=False):
        with open(self.mcm_cache_file, 'r') as f:
            cache = json.load(f)
        try:
            cache[meta_package_name]
        except KeyError:
            cache[meta_package_name] = {'packages': {}}

        joined_package_name = meta_package_name + '.' + package_name
        package_dir = os.path.join(self.mcm_package_packages_dir, joined_package_name)

        
        if get_attributes_from_cache:
            # Update the cache to midinstall status
            package_cache = cache[meta_package_name]['packages'][package_name]
            package_cache['status'] = 'midinstall'
        else:
            # The package is not installed at this point
            if package_name in cache[meta_package_name]['packages'].keys():
                raise Exception("Impossible - should only be invoked with uninstalled packages")

            # Create a new package_cache
            package_cache = {
                'status': 'midinstall',
                'package_dir': str(package_dir),
                'packages_dir': str(self.mcm_package_packages_dir),
                'tags': self.tags,
                'hostname': self.hostname
            }
            if target_dir is None:
                package_cache['target_dir'] = str(self.target_dir)
            else:
                package_cache['target_dir'] = str(target_dir)

        # Write the cache back
        cache[meta_package_name]['packages'][package_name] = package_cache
        with open(self.mcm_cache_file, 'w+') as f:
            json.dump(cache, f)

        # (re)install with scm
        scm_options = [
            'scm', '-f', '-y',
            '-t', package_cache['target_dir'],
            '-d', package_cache['packages_dir']
            ]

        if package_cache['hostname'] is not None:
            scm_options += ['-B', package_cache['hostname']]

        for tag in package_cache['tags']:
            scm_options += ['-T', tag]

        scm_options.append('install')
        scm_options.append(meta_package_name + '.' + package_name)

        logging.debug('Invoking {}'.format(scm_options))
        completed_process = subprocess.run(scm_options)
        if completed_process.returncode != 0:
            raise Exception('scm failed with error code {}'
                .format(completed_process.returncode))

        # Update the cache
        package_cache['status'] = 'installed'
        cache[meta_package_name]['packages'][package_name] = package_cache

        if self.hostname is not None:
            package_cache['hostname'] = self.hostname

        with open(self.mcm_cache_file, 'w') as f:
                json.dump(cache, f)

    def _invoke_scm_remove(self, meta_package_name, package_name):
        with open(self.mcm_cache_file, 'r') as f:
            cache = json.load(f)

        package_cache = cache[meta_package_name]['packages'][package_name]
        package_dir = package_cache['package_dir']
        packages_dir = self.mcm_package_packages_dir
        target_dir = package_cache['target_dir']
        tags = package_cache['tags']
        try:
            hostname = package_cache['hostname']
        except KeyError:
            hostname = None

        # Update package cache
        package_cache['status'] = 'midremove'
        cache[meta_package_name]['packages'][package_name] = package_cache

        with open(self.mcm_cache_file, 'w') as f:
            json.dump(cache, f)

        # Invoke scm
        scm_options = [
            'scm', '-f', '-y',
            '-t', target_dir,
            '-d', packages_dir
        ]

        if hostname is not None:
            scm_options += ['-B', self.hostname]

        for tag in tags:
            scm_options += ['-T', tag]

        scm_options.append('remove')
        scm_options.append(meta_package_name + '.' + package_name)

        logging.debug('Invoking {}'.format(scm_options))
        completed_process = subprocess.run(scm_options)
        if completed_process.returncode != 0:
            raise Exception('scm failed with error code {}'
                .format(completed_process.returncode))

        # Update package cache
        package_cache = {'status': 'loaded', 'package_dir': package_dir}
        cache[meta_package_name]['packages'][package_name] = package_cache

        with open(self.mcm_cache_file, 'w') as f:
            json.dump(cache, f)
                
    def load(self, uri_list, skip_if_loaded=True):
        if not isinstance(uri_list, list):
            uri_list = [uri_list]
        for uri in uri_list:
            logging.debug('Loading meta-package: {}'.format(uri))

            # Convert to absolute path uri
            if os.path.isfile(uri):
                uri = pathlib.Path(os.path.abspath(uri)).as_uri()

            data = urllib.request.urlopen(uri).read()
            meta_package_config = toml.loads(data.decode('utf-8'))
            file_name = meta_package_config['name']
            file_path = self._find_meta_package_by_name(file_name)
            if file_path is not None and skip_if_loaded:
                logging.warning('Module {} already loaded.  Skipping.'.format(file_name))
                continue

            # Get file name from url
            new_file_name = str(os.path.basename(urlparse(uri).path))
            new_file_path = os.path.join(self.mcm_package_configs_dir, new_file_name)

            jsonschema.validate(meta_package_config, self.meta_package_config_schema)

            # Remove the old file, if it exists
            os.remove(file_path)

            # Save new file
            with open(new_file_path, 'wb') as out_file:
                out_file.write(data)

            logging.debug('Loaded meta-package: {}'.format(uri))


    def unload(self, name_list):
        for name in name_list:
            # Get the meta-package name
            file_path = self._find_meta_package_by_name(name)
            if file_path is None:
                logging.warning('Module {} not loaded'.format(name))
                continue
           
            # Uninstall all associated packages
            self.remove([(name, '.*')], exit_if_not_installed=False)

            # Remove the meta-package itself
            os.remove(file_path)

    # package_list: [(meta_package_name, package_regex)]
    # load_only: if true, the package is loaded only and not installed
    # if_installed in ['exit', 'skip', 'reinstall']
    # Reinstall mode also ensures that only installed packages are reinstalled
    def install(self, package_list, load_only=False, if_installed='exit'):
        assert(if_installed in ['exit', 'skip', 'reinstall'])
        for (meta_package_name, package_regex) in package_list:
            file_path = self._find_meta_package_by_name(meta_package_name)
            if file_path is None:
                raise Exception('Module {} not loaded'.format(meta_package_name))

            meta_package = toml.load(file_path)
            raw_packages = [(x, meta_package['packages'][x])
                    for x in meta_package['packages'].keys()
                    if re.match(package_regex, x)]

            packages = []
            # Ensure the packages are not installed already
            for (package_name, package) in raw_packages:
                status = self._get_package_cache(meta_package_name, package_name)['status']

                if status in ['midinstall', 'midremove']:
                    raise Exception('Package {}.{} marked as {} - unless another mcm instance is running, the cache has been corrupted.  Run mcm cache-fix to repair.'.format(meta_package_name, package_name, status))

                if status == 'installed':
                    if if_installed == 'exit':
                        raise Exception('Package {}.{} already installed.'.format(meta_package_name, package_name, status))
                    elif if_installed == 'reinstall':
                        packages.append((package_name, package,))

                # not installed
                if status in ['notloaded', 'loaded']:
                    if if_installed != 'reinstall':
                        packages.append((package_name, package,))

            # Resolve package dependencies
            for (package_name, package) in packages:
                try:
                    dependencies = package['dependencies']
                except KeyError:
                    dependencies = []
                else:
                    logging.info('Resolving dependencies for package {}.{}'
                            .format(meta_package_name, package_name))

                dep_package_list = [(x['meta-package'], x['package-regex'])
                        for x in dependencies]
                self.install(dep_package_list, load_only=load_only, if_installed='skip')
                    
            # Load the packages
            for (package_name, package) in packages:
                status = self._get_package_cache(meta_package_name, package_name)['status']
                joined_package_name = meta_package_name + '.' + package_name
                package_dir = os.path.join(self.mcm_package_packages_dir, joined_package_name)

                # Get the target directory
                try:
                    target_dirs = package['target']
                except KeyError:
                    target_dir = self.target_dir
                else:
                    # Find the first existant target_dir
                    found = False
                    for t in target_dirs:
                        target_dir = os.path.abspath(os.path.expandvars(t))
                        if os.path.isdir(target_dir):
                            found = True
                            break
                    if not found:
                        raise Exception("No valid target dir found for package {}.{}".format(meta_package_name, package_name))

                if status == 'notloaded':
                    logging.info('Loading package {}.{}'
                            .format(meta_package_name, package_name))

                    # Find the installation mechanism, according to the preferred order
                    possible_installation_mechanisms = []
                    try:
                        installation_mechanisms = package['installation-mechanisms']
                    except KeyError:
                        raise Exception('Meta-package {} has no installation mechanisms'.format(meta_package_name))
                    if installation_mechanisms == []:
                        raise Exception('Meta-package {} has no installation mechanisms'.format(meta_package_name))

                    loaded = False
                    for name, val in installation_mechanisms.items():
                        if name == 'git':
                            if not USING_GITPYTHON:
                                possible_installation_mechanisms.append('git')
                            else:
                                logging.debug('Installing package {}.{} with git'
                                        .format(meta_package_name, package_name))

                                # Download using git
                                uri = val['uri']
                                git.Git(package_dir).clone(uri)
                                loaded = True

                        elif name == 'tar':
                            if not USING_TARFILE:
                                possible_installation_mechanisms.append('tar')
                            else:
                                logging.debug('Installing package {}.{} with tar'
                                        .format(meta_package_name, package_name))

                                # Get the tarball
                                uri = val['uri']
                                if os.path.isfile(uri):
                                    uri = pathlib.Path(os.path.abspath(uri)).as_uri()

                                data = urllib.request.urlopen(uri).read()

                                # Extract the tarball to package_dir
                                file_like_object = io.BytesIO(data)
                                tar_archive = tarfile.open(fileobj=file_like_object)
                                tar_archive.extractall(package_dir)
                                logging.debug('Extracted package {}.{} to {}'
                                        .format(meta_package_name, package_name, package_dir))
                                loaded = True

                        else:
                            logging.warning('Unrecognised installation mechanism {} in package {}.{}'.format(name, meta_package_name, package_name))

                    if not loaded:
                        if possible_installation_mechanisms == []:
                            raise Exception('Meta-package could not be loaded: no valid installation mechanisms of: {}'.format(installation_mechanisms))
                        else:
                            raise Exception('Meta-package could not be loaded, but uses the following valid installation mechanisms: {}'.format(possible_installation_mechanisms))

                else:
                    logging.info('Package {}.{} already loaded'
                            .format(meta_package_name, package_name))

                # Install the package
                if not load_only:
                    # Install the package with scm
                    self._invoke_scm_install(meta_package_name, package_name, target_dir, get_attributes_from_cache=(if_installed == 'reinstall'))
                else:
                    # Read the cache
                    with open(self.mcm_cache_file, 'r') as f:
                        cache = json.load(f)
                    try:
                        cache[meta_package_name]
                    except KeyError:
                        cache[meta_package_name] = {'packages': {}}

                    # Update the cache to loaded
                    package_cache = {
                        'status': 'loaded'
                    }
                    cache[meta_package_name]['packages'][package_name] = package_cache

                    with open(self.mcm_cache_file, 'w+') as f:
                        json.dump(cache, f)

                
	# if exit_if_not_installed, will raise an exception if any specified
	# package in package_list does not exist
    def remove(self, package_list, uninstall_only=False, exit_if_not_installed=True):
        for (meta_package_name, package_regex) in package_list:
            file_path = self._find_meta_package_by_name(meta_package_name)
            if file_path is None:
                raise Exception('Module {} not loaded'.format(meta_package_name))

            meta_package = toml.load(file_path)
            packages = [(x, meta_package['packages'][x])
                    for x in meta_package['packages'].keys()
                    if re.match(package_regex, x)]

            # Ensure the packages are installed already
            for (package_name, _) in packages:
                status = self._get_package_cache(meta_package_name, package_regex)['status']
                if status in ['midinstall', 'midremove']:
                    raise Exception('Package {}.{} marked as {} - unless another mcm instance is running, the cache has been corrupted.  Run mcm cache-fix to repair.'.format(meta_package_name, package_name, status))

                if status in ['notloaded', 'loaded']:
                    if exit_if_not_installed:
                        raise Exception('Package {}.{} already not installed.'.format(meta_package_name, package_name, status))
                    else:
                        continue

                # TODO: Resolve package dependencies. For now, uninstalling is more manual

                # Uninstall the package
                self._invoke_scm_remove(meta_package_name, package_name)

                # Remove the package
                if not uninstall_only:
                    logging.debug('Unloading package {}.{}'.format(meta_package_name, package_name))
                    with open(self.mcm_cache_file, 'r') as f:
                        cache = json.load(f)
                    package_dir = cache[meta_package_name]['packages'][package_name]['package_dir']
                    logging.debug('Removing package at {}'.format(package_dir))
                    shutil.rmtree(package_dir)

                    del cache[meta_package_name]['packages'][package_name]
                    with open(self.mcm_cache_file, 'w') as f:
                        cache = json.dump(cache, f)

    # Find all installed packages and re-install them
    def update(self, package_list):
        def update_meta_package(meta_package_name):
            logging.info("Updating meta-package {}".format(meta_package_name))
            uri = self._get_meta_package_by_name(meta_package_name)['uri']
            self.load(uri, skip_if_loaded=False)

        packages = self.list_packages(pretty_print=False)
        if len(package_list) == 0:
            # Update all packages
            for meta_package_name in packages.keys():
                update_meta_package(meta_package_name)
                self.install([(meta_package_name, '.*')], if_installed='reinstall')
        else:
            for (meta_package_name, package_regex) in package_list:
                if package_regex == None:
                    # Update just the meta-package
                    update_meta_package(meta_package_name)
                else:
                    # Update just the packages
                    self.install([(meta_package_name, '.*')], if_installed='reinstall')

    def list_packages(self, pretty_print=True):
        # Locate all loaded meta-packages
        # Construct map of meta-package name to directory
    
        #   meta_packages = {
        #       'meta_package_name': {
        #           'path': '/path/to/meta-package',
        #           'packages': {
        #               'package-name': {
        #                   'status': 'installed',
        #                   'path': '/package/path',
        #                   ...
        #               }
        #           }
        #       }
        #   }
        
        meta_packages = {}
        for file_name in os.listdir(self.mcm_package_configs_dir):
            # Locate meta-package
            file_dir = os.path.abspath(os.path.join(self.mcm_package_configs_dir, file_name))
            try:
                meta_package = toml.load(file_dir)
            except Exception as e:
                logging.warning('Junk file {} in the mcm package configs dir: {}'
                    .format(file_dir, self.mcm_package_configs_dir))
                continue

            meta_package_name = meta_package['name']
            assert(meta_package_name not in meta_packages.keys())
            meta_packages[meta_package_name] = { 'path': file_dir, 'packages': {} }

            # Find all packages in meta-package
            for package_name in meta_package['packages'].keys():
                package_cache = self._get_package_cache(meta_package_name, package_name)
                meta_packages[meta_package_name]['packages'][package_name] = package_cache

        if pretty_print:
            # Print main information
            print("data directory: {}".format(self.mcm_dir))
            print("cache directory: {}".format(self.mcm_cache_dir))
            print()

            # Print package information
            for meta_package_name, meta_package in meta_packages.items():
                print("{}: {}".format(meta_package_name, meta_package['path']))
                for package_name, package_cache in meta_package['packages'].items():
                    if 'package_dir' in meta_package.keys():
                        print("    {}: {}".format(package_name, package_cache['package_dir']))
                    else:
                        print("    {}".format(package_name))

                    for k, v in package_cache.items():
                        if k in ['package_dir', 'packages_dir']:
                            continue
                        print("        {}: {}".format(k, v))
        else:
            return meta_packages

def main():
    default_mcm_dir = os.path.join(xdg.XDG_DATA_HOME, 'mcm2')

    parser = argparse.ArgumentParser(description='Meta configuration manager for scm.')
    parser.add_argument('-v', '--verbose', action='count', default=0, dest='verbose')
    parser.add_argument('-d', type=pathlib.PosixPath, metavar='MCM_DIR',
        help='The MCM data directory (default {})'.format(default_mcm_dir),
        dest='mcm_dir')
    parser.add_argument('-t', type=pathlib.PosixPath, metavar='TARGET',
        help='MCM target directory.  Guaranteed to not install dotfiles outside this directory.',
        dest='target_dir')
    parser.add_argument('-B, --hostname', metavar='NAME', 
        help='Override the computer\'s hostname. Affects which host-specific files/hooks are used.',
        dest='hostname')
    parser.add_argument('-T, --tag', action='append', metavar='TAG',
        help='Specify tags to enable for underlying dotfile configurations.',
        dest='tags')

    subparsers = parser.add_subparsers()

    parser_load = subparsers.add_parser('load', help='Loads a new meta-package into mcm')
    parser_load.add_argument('uri', metavar='META_PACKAGE_URI', type=str, nargs='+')
    parser_load.set_defaults(func='load')

    parser_unload = subparsers.add_parser('unload', help='Unloads and removes an existing meta-package from mcm')
    parser_unload.add_argument('name', metavar='META_PACKAGE_NAME', type=str, nargs='+')
    parser_unload.set_defaults(func='unload')

    parser_install = subparsers.add_parser('install', help='Downloads and installs a particular package from the given meta-package')
    parser_install.add_argument('-l, --load-only', action='store_true', help='Only load the packages, do not install them', dest='load_only')
    parser_install.add_argument('package', metavar='META_PACKAGE.PACKAGE', type=str,
            nargs='+', default=[],
            help='The meta-package and the desired package, in the format meta-package.package')
    parser_install.set_defaults(func='install')

    parser_remove = subparsers.add_parser('remove', help='Removes and uninstalls a particular package from the given meta-package')
    parser_remove.add_argument('package', metavar='META_PACKAGE.PACKAGE', type=str,
            nargs='+', default=[],
            help='The meta-package and the desired package, in the format meta-package.package')
    parser_remove.set_defaults(func='remove')

    parser_update = subparsers.add_parser('update', help='Updates installed packages.  If no arguments are supplied, updates all loaded meta-packages and all installed packages.  If only a meta-package is supplied, updates that meta-package.  If a meta-package.package is supplied, updates that package.')
    parser_update.add_argument('update_package', metavar='META_PACKAGE[.PACKAGE]', type=str,
            nargs='*', default=[],
            help='The meta-package and the desired package, in the format meta-package[.package]')
    parser_update.set_defaults(func='update')

    parser_list = subparsers.add_parser('list', help='Lists all installed and non-installed packages from all loaded meta-packages')
    parser_list.set_defaults(func='list_packages')

    args = parser.parse_args()
    
    verbosities = [logging.WARNING, logging.INFO, logging.DEBUG]
    logging.getLogger().setLevel(verbosities[min(args.verbose, len(verbosities)-1)])

    logging.debug(args)
    mcm = Mcm(mcm_dir=args.mcm_dir,
            target_dir=args.target_dir, hostname=args.hostname, tags=args.tags)
    try:
        args.func
    except AttributeError:
        parser.print_help(sys.stderr)
        sys.exit(1)

    def _tupleise(arg):
        t = arg.split('.', 1)
        if len(t) != 2:
            raise Exception("Must supply fully qualified package name i.e. META-PACKAGE.PACKAGE")
        return tuple(t)

    def _update_tupleise(arg):
        t = arg.split('.', 1)
        if len(t) < 2:
            t.append(None)
        assert(len(t) == 2)
        return tuple(t)

    try:
        package_list = [_tupleise(x) for x in args.package] 
    except AttributeError:
        pass

    try:
        update_package_list = [_update_tupleise(x) for x in args.update_package]
    except AttributeError:
        pass

    if args.func == 'load':
        mcm.load(args.uri)
    elif args.func == 'unload':
        mcm.unload(args.name)
    elif args.func == 'install':
        mcm.install(package_list, args.load_only)
    elif args.func == 'remove':
        mcm.remove(package_list)
    elif args.func == 'update':
        mcm.update(update_package_list)
    elif args.func == 'list_packages':
        mcm.list_packages()

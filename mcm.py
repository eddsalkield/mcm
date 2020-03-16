#!/usr/bin/python3
import argparse
import xdg
import os
import pathlib
import logging
import urllib.request
import toml
import sys


class Mcm():
    def __init__(self, verbosity=0, mcm_dir=None, target_dir=None, hostname=None, tags=None):
        if mcm_dir is None:
            mcm_dir = os.path.join(xdg.XDG_DATA_HOME, 'mcm')
        if target_dir is None:
            target_dir = target_dir=pathlib.Path.home()
        if tags is None:
            tags = []

        self.verbosity = verbosity
        self.mcm_dir = mcm_dir
        self.mcm_package_configs_dir = os.path.join(mcm_dir, 'configs')
        self.target_dir = target_dir
        self.hostname = hostname
        self.tags = tags

    def _find_meta_package_by_name(self, meta_package_name):
        for file_name in os.listdir(self.mcm_package_configs_dir):
            file_dir = os.path.abspath(os.path.join(self.mcm_package_configs_dir, file_name))
            if toml.load(file_dir)['name'] == meta_package_name:
                return file_dir
        return None
                
    def load(self, uri_list):
        for uri in uri_list:
            logging.debug("Loading meta-package: {}".format(uri))

            data = urllib.request.urlopen(uri).read()
            file_name = toml.loads(data.decode('utf-8'))['name']
            file_path = self._find_meta_package_by_name(file_name)
            if file_path is not None:
                logging.warning("Module {} already loaded".format(file_name))
                continue

            with open(file_path, 'wb') as out_file:
                out_file.write(data)

            logging.debug("Loaded meta-package: {}".format(uri))


    def unload(self, name_list):
        for name in name_list:
            # Get the meta-package name
            file_path = self._find_meta_package_by_name(name)
            if file_path is None:
                logging.warning("Module {} not loaded".format(name))
           
            # Uninstall all associated packages
            self.remove([name+'.*'])

            # Remove the meta-package itself
            os.remove(file_path)

    def install(self, package_list):
        pass

    def remove(self, package_list):
        pass

    def update(self, package_list, all_packages=False):
        pass

    def list_packages(self):
        pass


if __name__ == '__main__':
    default_mcm_dir = os.path.join(xdg.XDG_DATA_HOME, 'mcm')

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
    parser_load.add_argument("uri", metavar="META_PACKAGE_URI", type=str, nargs='+')
    parser_load.set_defaults(func='load')

    parser_unload = subparsers.add_parser('unload', help='Unloads and removes an existing meta-package from mcm')
    parser_unload.add_argument("name", metavar="META_PACKAGE_NAME", type=str, nargs='+')
    parser_unload.set_defaults(func='unload')

    parser_install = subparsers.add_parser('install', help='Downloads and installs a particular package from the given meta-package')
    parser_install.add_argument("package", metavar="META_PACKAGE.PACKAGE", type=str, nargs='+', help="The meta-package and the desired package, in the format meta-package.package")
    parser_install.set_defaults(func='install')

    parser_remove = subparsers.add_parser('remove', help='Removes and uninstalls a particular package from the given meta-package')
    parser_remove.add_argument("package", metavar="META_PACKAGE.PACKAGE", type=str, nargs='+', help="The meta-package and the desired package, in the format meta-package.package")
    parser_remove.set_defaults(func='remove')

    parser_update = subparsers.add_parser('update', help='Updates installed packages')
    parser_update.add_argument("-a, --all", action='store_false', help='Update all installed packages', dest='all_packages')
    parser_update.add_argument("package", metavar="META_PACKAGE.PACKAGE", type=str, nargs='+', help="The meta-package and the desired package, in the format meta-package.package")
    parser_update.set_defaults(func='update')

    parser_list = subparsers.add_parser('list', help='Lists all installed and non-installed packages from all loaded meta-packages')
    parser_list.set_defaults(func='list_packages')

    args = parser.parse_args()

    logging.debug(args)
    mcm = Mcm(verbosity=args.verbose, mcm_dir=args.mcm_dir,
            target_dir=args.target_dir, hostname=args.hostname, tags=args.tags)
    try:
        args.func
    except AttributeError:
        parser.print_help(sys.stderr)
        sys.exit(1)

    if args.func == 'load':
        mcm.load(args.uri)
    elif args.func == 'unload':
        mcm.unload(args.name)
    elif args.func == 'install':
        mcm.install(args.package)
    elif args.func == 'remove':
        mcm.remove(args.package)
    elif args.func == 'update':
        mcm.update(args.package, args.all_packages)
    elif args.func == 'list_packages':
        mcm.list_packages()

    #args.func(args)

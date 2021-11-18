#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

from ipaperftest.core.main import Registry


class PluginRegistry(Registry):
    def initialize(self):
        pass


registry = PluginRegistry()

#
# Copyright (C) 2021 FreeIPA Contributors see COPYING for license
#

import click
import pkg_resources
import sys
import traceback

from ipaperftest.core.plugin import Result, Results
from ipaperftest.core.output import output_registry
from ipaperftest.core.constants import (
    SUCCESS,
    CRITICAL
)


class Registry:
    """
    A decorator that makes plugins available to the API

    Usage::

        register = Registry()

        @register()
        class some_plugin(...):
            ...
    """
    def __init__(self):
        self.plugins = []

    def __call__(self, cls):
        if not callable(cls):
            raise TypeError('plugin must be callable; got %r' % cls)
        self.plugins.append(cls)
        return cls

    def get_plugins(self):
        for plugincls in self.plugins:
            yield plugincls(self)


def find_registries(entry_points):
    registries = {}
    for entry_point in entry_points:
        registries.update({
            ep.name: ep.resolve()
            for ep in pkg_resources.iter_entry_points(entry_point)
        })
    return registries


def find_plugins(name, registry):
    for ep in pkg_resources.iter_entry_points(name):
        # load module
        ep.load()
    return registry.get_plugins()


class RunTest:
    def __init__(self, entry_points):
        """Initialize class variables

          entry_points: A list of entry points to find plugins
        """
        self.entry_points = entry_points
        self.results = Results()

    def run(self, ctx):
        plugins = []

        for name, registry in find_registries(self.entry_points).items():
            registry.initialize()
            for plugin in find_plugins(name, registry):
                plugins.append(plugin)

        # TODO: short-circuit this and run directly above. Easier to
        #       troubleshoot here
        for plugin in plugins:
            if plugin.__class__.__name__ == ctx.params['test']:
                try:
                    for result in plugin.execute(ctx):
                        self.results.add(result)
                except Exception:
                    except_res = Result(plugin, CRITICAL, exception=traceback.format_exc())
                    self.results.add(except_res)

        output = None
        for out in output_registry.plugins:
            if out.__name__.lower() == ctx.params['results_format']:
                output = out(ctx.params['results_output_file'])
                break

        output.render(self.results)

        ret_val = 0
        for result in self.results.results:
            if result.result != SUCCESS:
                ret_val = 1
                break

        sys.exit(ret_val)


@click.command("cli", context_settings={"show_default": True})
@click.option("--test", default="EnrollmentTest", help="Test to execute.")
@click.option(
    "--client-image",
    help="Image to use for clients.",
)
@click.option(
    "--server-image",
    help="Image to use for server.",
)
@click.option("--amount", default=1, help="Size of the test.")
@click.option(
    "--replicas",
    default=0,
    type=click.IntRange(0, 2),
    help="Number of replicas to create.",
)
@click.option("--threads", default=10, help="Threads to run per client during AuthenticationTest.")
@click.option("--ad-threads", default=0, help="Active Directory login threads "
                                              "to run per client during AuthenticationTest.")
@click.option("--command", help="Command to execute during APITest.")
@click.option(
    "--results-format",
    help="Format to use for results output",
    type=click.Choice(["json", "human"], case_sensitive=False), default="json"
)
@click.option(
    "--results-output-file",
    help="File to write results output to",
)
@click.option(
    "--custom-repo-url",
    help="URL from custom repo to be configured on the server hosts. "
         "Make sure N-V-R is higher than the packages available in the "
         "server image so that your packages are used.",
    default=""
)
@click.option(
    "--provider",
    help="Provider to use during test execution",
    type=click.Choice(["vagrant", "idmci"], case_sensitive=False), default="idmci"
)
@click.option(
    "--private-key",
    help="Private key needed to access VMs in case the default is not enough.",
)
@click.option(
    "--sequential",
    help="Run APITest commands sequentially from a single client.",
    is_flag=True
)
@click.option(
    "--idmci-lifetime",
    help="Lifetime in hours of IdM-CI hosts.",
    default=8,
)
@click.pass_context
def main(
    ctx,
    test,
    command,
    private_key,
    client_image,
    server_image,
    sequential,
    amount=1,
    threads=10,
    ad_threads=0,
    replicas=0,
    results_format="json",
    results_output_file=None,
    custom_repo_url="",
    provider="idmci",
    idmci_lifetime=8,
):

    tests = RunTest(['ipaperftest.registry'])
    try:
        tests.run(ctx)
    except RuntimeError:
        sys.exit(1)

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
        for name, registry in find_registries(self.entry_points).items():
            registry.initialize()
            for plugin in find_plugins(name, registry):
                if plugin.__class__.__name__ != ctx.params['test']:
                    continue
                selected_plugin = plugin
                try:
                    self.results.add(Result(plugin, SUCCESS, args=sys.argv))
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

        # Output first to results_output_file / stdout, and then to runner_metadata
        # After that, build the tarfile will all the logs
        output.render(self.results)
        output.filename = "runner_metadata/test_result"
        output.render(self.results)
        selected_plugin.archive_results(ctx)

        ret_val = 0
        for result in self.results.results:
            if result.result != SUCCESS:
                ret_val = 1
                break

        sys.exit(ret_val)


@click.command("cli", context_settings={"show_default": True})
@click.option("--test", default="EnrollmentTest", help="Test to execute.",
              type=click.Choice(["EnrollmentTest",
                                 "APITest",
                                 "AuthenticationTest",
                                 "CertIssuanceTest",
                                 "GroupSizeTest"]))
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
    type=click.IntRange(0, 64),
    help="Number of replicas to create.",
)
@click.option("--threads", default=10, help="Threads to run per client during AuthenticationTest.")
@click.option("--ad-threads", default=0, help="Active Directory login threads "
                                              "to run per client during AuthenticationTest.")
@click.option("--sizelimit", default=100, help="IPA search size limit")
@click.option("--disable-selinux", default=False, is_flag=True,
              help="Disable the SSSD SELinux provider in all clients, enable forking in pamtest")
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
@click.option(
    "--auth-spread",
    help="Time range in minutes to spread auths in AuthenticationTest",
    default=0,
)
@click.option(
    "--expected-result-type",
    help="Type of expected result.",
    type=click.Choice(["time", "time_unit", "no_errors"]), default="no_errors"
)
@click.option(
    "--expected-result",
    help="Expected result of the test, in seconds.",
    type=click.FLOAT
)
@click.option(
    "--number-of-subgroups",
    help="Number of sub groups for Groupsize test",
    default=0,
)
@click.option("--cert-requests", default=0, help="Number of certificates to request")
@click.option("--wsgi-processes", default=4, help="Number of WSGI processes")
@click.pass_context
def main(
    ctx,
    test,
    command,
    private_key,
    client_image,
    server_image,
    sequential,
    expected_result,
    amount=1,
    threads=10,
    ad_threads=0,
    sizelimit=100,
    disable_selinux=False,
    replicas=0,
    results_format="json",
    results_output_file=None,
    custom_repo_url="",
    provider="idmci",
    idmci_lifetime=8,
    auth_spread=0,
    expected_result_type="no_errors",
    number_of_subgroups=0,
    cert_requests=0,
    wsgi_processes=4,
):

    tests = RunTest(['ipaperftest.registry'])
    try:
        tests.run(ctx)
    except RuntimeError:
        sys.exit(1)

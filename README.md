# FreeIPA Performance Testing

Collection of performance and scalability-related testing scripts.

## Dependencies

This tool uses Vagrant and Libvirt to deploy VMs for testing.
The controller must have the following software installed:

* `vagrant`
* `ansible`
* `libvirt`
* `git`
* `rsync`
* Vagrant plugins
   * `vagrant-libvirt`
   * `winrm` (for AD support)
   * `winrm-elevated` (for AD support)


## Usage

```
Usage: ipaperftest [OPTIONS]

Options:
  --test TEXT                    Test to execute.  [default: EnrollmentTest]
  --client-image TEXT            Vagrant image to use for clients.  [default:
                                 antorres/fedora-34-ipa-client]
  --server-image TEXT            Vagrant image to use for server.  [default:
                                 antorres/fedora-34-ipa-client]
  --amount INTEGER               Size of the test.  [default: 1]
  --replicas INTEGER RANGE       Number of replicas to create.  [default:
                                 0;0<=x<=2]
  --threads INTEGER              Threads to run per client during
                                 AuthenticationTest.  [default: 10]
  --command TEXT                 Command to execute during APITest.
  --private-key TEXT             Private key needed to access VMs in case the
                                 Vagrant default is not enough.
  --results-format [json|human]  Format to use for results output  [default:
                                 json]
  --results-output-file TEXT     File to write results output to
  --custom-repo-url TEXT         URL from custom repo to be configured on the
                                 server hosts  [default: ]
  --help                         Show this message and exit.  [default: False]
```

## Capturing results

After executing the script, a `sync` directory will be created. There you will find logs gathered from all the machines
deployed, including performance monitoring using SAR.

A tarball will be created containing the sync directory and metadata like Ansible playbooks and Vagrantfile.

## Development

The package can be tested and developed in a python virtual environment.

To create the virtual environment run:

```
$ python3 -m venv --system-site-packages venv
$ venv/bin/pip install -e .
```

To use the environment:

```
$ source venv/bin/activate
```

To run the tool:

```
$ source venv/bin/activate
$ ipaperftest
```

## Sample usage

To run an enrollment test, with 100 clients and 2 replicas:

```
$ ipaperftest --test EnrollmentTest --replicas 2 --amount 100
```

## Available tests

### EnrollmentTest

Try to enroll n clients simultaneously, n being the amount especified using the `amount` option.
During this test, n client machines are created and configurated.
After this, they are all scheduled to launch `ipa-client-install` at the same time. A wait is added to ensure
all machines are properly configured before the client installation time. Once all the install processes exit,
the results are retrieved. To ensure that enrollment went well on both ends, clients successes are counted and
compared against the output of `ipa host-find` on the server.

If using replicas, the distribution of enrollments between servers will be shown after the test.

### AuthenticationTest

Perform authentication attempts against the server. The number of clients deployed is set using the `amount` option,
and the amount of authentication threads per client is defined using the `threads` option, so the total amount of
authentication attemps performed is `amount` * `threads`.

Before launching the authentications both server and clients are configured. Test users are created using the
`create-test-data.py` and `set-password.py` scripts, as explained below. After this, authentications are attempted
using the `pamtest` tool. A file named `pamtest.log` will be created for each client, containing logs from this run.

After the test execution, percentage of succeeded attempts will be shown, both per client and in total.

### APITest

This tests runs the same command n times simultaneously. The command is specified using the `command` option. The
wildcard `{id}` is permitted for commands that required variability to run properly (for example, it can be used
as a username so that the `user-add` command can be run multiple times without failing). The amount of commands to
run is set using the `amount` options, and these commands will be run from clients deployed before the test. Each
client deployed will run a maximum of 50 commands. These commands are scheduled on the client using the `at` tool.

After the execution of the test, output from the commands will be written to the `sync` directory.

## Creating test users

For client authentication test we need a lot of users to test against.
The combination of two scripts will create the users needed for testing
with identical, unexpired passwords.

In order to set passwords using a pre-hashed password IPA needs to
be in migration mode:

```
$ kinit admin
$ ipa config-mod --enable-migration=true
```

Create 10 users for each of 500 hosts. The format of the uid is
user#client@.<domain>.

```
$ ./create-test-data.py  > user.ldif
$ ldapadd -x -D 'cn=directory manager' -W < user.ldif
```

Time to add depends on the server but for me it was ~9 minutes.

Now reset all Kerberos credentials to the value of 'password':

```
./set-password.py --dm-password <Directory Manager password>
```

Time to reset the passwords is ~11 minutes. This is done as the
DM user requesting a keytab for each user which will set the
Kerberos credentails. The LDAP password is set on the import.

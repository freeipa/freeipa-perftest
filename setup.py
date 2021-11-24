from setuptools import setup


setup(
    name='ipaperftest',
    version='0.1',
    namespace_packages=['ipaperftest', ],
    package_dir={'': 'src'},
    packages=[
        'ipaperftest.core',
    ],
    entry_points={
        # creates bin/ipaperftest
        'console_scripts': [
            'ipaperftest = ipaperftest.core.main:main',
        ],
        # subsystem registries
        'ipaperftest.registry': [
            'ipaperftest.plugins = ipaperftest.plugins.registry:registry',
        ],
        # plugin modules for ipaperftest.plugins registry
        'ipaperftest.plugins': [
            'apitest = ipaperftest.plugins.apitest',
            'authenticationtest = ipaperftest.plugins.authenticationtest',
            'enrollmenttest = ipaperftest.plugins.enrollmenttest',
        ],
    },
    install_requires=[
        'click',
    ],
    classifiers=[
        'Programming Language :: Python :: 3.8',
    ],
    python_requires='!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*',
)

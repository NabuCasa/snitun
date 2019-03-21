from setuptools import setup

VERSION = "0.18"

setup(
    name="snitun",
    version=VERSION,
    license="GPL v3",
    author="Nabu Casa, Inc.",
    author_email="opensource@nabucasa.com",
    url="https://www.nabucasa.com/",
    download_url="https://github.com/NabuCasa/snitun/tarball/{}".format(
        VERSION),
    description=("SNI proxy with TCP multiplexer"),
    long_description=(""),
    classifiers=[
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    keywords=["sni", "proxy", "multiplexer", "tls"],
    zip_safe=False,
    platforms="any",
    packages=[
        "snitun", "snitun.server", "snitun.client", "snitun.multiplexer",
        "snitun.utils"
    ],
    install_requires=[
        "attrs>=18.2.0", "async_timeout>=3.0.1", "cryptography>=2.5"
    ],
    include_package_data=True)

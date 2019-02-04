from setuptools import setup

setup(
    name="SniTun",
    version="0.1",
    license="GPL v3",
    author="Nabu Casa, Inc.",
    author_email="social@nabucasa.com",
    url="https://www.nabucasa.com/",
    description=("SNI proxy with TCP multiplexer"),
    long_description=(""),
    classifiers=[
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Topic :: Home Automation"
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Scientific/Engineering :: Atmospheric Science",
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.7",
    ],
    keywords=["sni", "proxy", "multiplexer"],
    zip_safe=False,
    platforms="any",
    packages=[
        "snitun", "snitun.server", "snitun.client", "snitun.multiplexer",
        "snitun.utils"
    ],
    install_requires=[
        "attrs==18.2.0", "async_timeout==3.0.1", "cryptography==2.5"
    ],
    include_package_data=True)

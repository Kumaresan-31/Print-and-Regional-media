from setuptools import setup, find_packages

setup(
    name="harvester",
    version="2.1.0",
    package_dir={"": "backend"},
    packages=find_packages(where="backend"),
)

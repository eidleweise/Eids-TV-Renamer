from setuptools import setup, find_packages

setup(
    name="tvrenamer",
    version="0.1.0",
    description="TV episode renamer",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "tvrenamer=tvrenamer.cli:main",
        ],
    },
    install_requires=[
        'toml;python_version<"3.11"',
    ],
)

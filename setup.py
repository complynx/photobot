from setuptools import setup, find_packages

setup(
    name="photobot",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "python-telegram-bot[job-queue]==20.3",
        "fluent.runtime==0.4",
        "tornado==6.3",
        "pyyaml==6.0",
        "pillow==9.5",
        "numpy==1.24",
        "pydantic==1.10",
    ],
)

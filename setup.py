"""Junior Aladdin - NIFTY 50 auto market-observation + trading system."""
from setuptools import setup, find_packages

setup(
    name="junior_aladdin",
    version="0.1.0",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "pyyaml>=6.0",
        "smartapi-python>=1.2.0",
        "websockets>=12.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0",
            "pytest-cov>=5.0",
            "mypy>=1.8",
            "ruff>=0.3",
        ],
    },
)

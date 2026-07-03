from setuptools import setup, find_packages

setup(
    name="codegen",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.10",
    install_requires=[
        "pyyaml>=6.0",
        "pydantic>=2.0",
        "jinja2>=3.0",
    ],
    entry_points={
        "console_scripts": [
            "codegen=codegen.cli:main",
        ],
    },
)

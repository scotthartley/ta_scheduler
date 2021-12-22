from setuptools import setup, find_packages


# def readme():
#     with open("README.rst", encoding='utf8') as file:
#         return file.read()


exec(open('ta_scheduler/_version.py').read())

setup(name='ta_scheduler',
      version=__version__,
      description='Generate and prioritize meeting schedules',
      # long_description=readme(),
      author='Scott Hartley',
      author_email='scott.hartley@miamioh.edu',
      url='https://hartleygroup.org',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      entry_points={
          'console_scripts': [
              'ta_sched = ta_scheduler:ta_sched',
          ]
      },
      install_requires=[
      ],
      python_requires=">=3.1",
      )

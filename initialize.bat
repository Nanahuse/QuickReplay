cd extern\python-capture-device-list
python .\setup_distutils.py install
cd ..\ndi-python
python .\setup.py install
cd ..\..
python -m pip install -r requirements.txt
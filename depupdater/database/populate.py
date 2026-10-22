import csv
import subprocess
import xml.etree.ElementTree as ET
import os

from depupdater.database.query import insert_dependencies_into_mongo

import depupdater.paths as constants
from depupdater.database.download_pom import download_pom_one


def populate_dep(go, ao, vo):
    """get the dependencies of an artifact and store them in the database
    Args:
        go (str): groupId
        ao (str): artifactId
        vo (str): version
    """
    os.makedirs(constants.POM_PATH, exist_ok=True)
    gav = go+'|'+ao+'|'+vo
    can_download = download_pom_one(gav)
    if not can_download:
        # cann't download pom.xml
        with open(os.path.join(constants.POM_PATH,'errored.csv'), 'a') as fc:
            csv.writer(fc).writerow([gav.replace('|', ':')])
        return []

    downloaded_pom = os.path.join(constants.POM_PATH, ao+'-'+vo+'.pom')
    pom_path = os.path.join(constants.POM_PATH, 'pom.xml')
    if not os.path.exists(downloaded_pom):
        return
    os.rename(downloaded_pom, pom_path)
    try:
        # get the effective pom from the pom.xml
        print(f'extracting dependencies of {gav}...')
        output = subprocess.check_output(['mvn', 'help:effective-pom', '-Doutput=tmp_pom.xml'],
                                         stderr=subprocess.STDOUT, cwd=constants.POM_PATH)
        # print(output)
    except:
        with open(os.path.join(constants.POM_PATH,'errored.csv'), 'a') as fc:
            csv.writer(fc).writerow([gav.replace('|', ':')])
    try:
        mytree = ET.parse(os.path.join(constants.POM_PATH, 'tmp_pom.xml'))
        root = mytree.getroot()
        dependencies = []
        order = 1
        for child in root:
            if 'dependencies' in child.tag:
                for dep in child:
                    each = {}
                    s = ''
                    opt=''
                    for ele in dep:
                        if 'groupId' in ele.tag:
                            g = ele.text
                        if 'artifactId' in ele.tag:
                            a = ele.text
                        if 'version' in ele.tag:
                            v = ele.text
                        if 'isoptional' in ele.tag:
                            opt = ele.text
                        if 'scope' in ele.tag:
                            s = ele.text
                    gav_d = g+':'+a+':'+v
                    if s=='':
                        s = 'compile'
                    # if s== 'test':
                    #     continue
                    if opt.lower() =='true':
                        opt = 'true'
                    else:
                        opt = 'false'
                    each['dep'] = gav_d
                    each['dScope'] = s
                    each['dType'] = "dependency"
                    each['isoptional'] = opt
                    each['order'] = str(order)
                    each['exclusion'] = []
                    dependencies.append(each)
                    order += 1

        os.remove(pom_path)

        insert_dependencies_into_mongo(go, ao, vo, dependencies)
    except Exception as e:
        print(gav, e)

    print(f'dependencies of {gav} got')

    return dependencies

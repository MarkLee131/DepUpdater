"""download a pom.xml accroding to the gav"""
import os
import subprocess
import shutil
import depupdater.paths as constants
from depupdater.paths import M2_PATH

def download_pom_one(jar_info):
    print('Downloading', jar_info)

    group_id, artifact_id, version_name = jar_info.split('|')
    local_path = constants.POM_PATH
    #os.path.join(download_path, group_id, artifact_id, version_name)
    # os.makedirs(local_path, exist_ok=True)

    # if os.path.exists(os.path.join(local_path, artifact_id+'-'+version_name+'.jar')):
    #     return
    try:
        subprocess.check_output([
            'mvn', 'dependency:get', f'-DgroupId={group_id}',
            f'-DartifactId={artifact_id}', f'-Dversion={version_name}',
            '-Dtransitive=false', f'-Ddest={local_path}',
            '-DremoteRepositories=https://repo1.maven.org/maven2/', '-Dpackaging=pom',
        ])

        # print(result)
        if not os.path.exists(os.path.join(local_path, artifact_id+'-'+version_name+'.pom')):
            shutil.copyfile(M2_PATH+group_id.replace('.', '/')+'/'+artifact_id+'/'+version_name+ '/'+ artifact_id+'-'+version_name+'.pom', os.path.join(local_path, artifact_id+'-'+version_name+'.pom'))
        return True
    except Exception as e:
        print(e)
        return False

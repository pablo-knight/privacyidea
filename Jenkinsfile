pipeline {
    agent any

    stages {
        stage ('Build Ubuntu16') {

            steps {
                echo 'building xenial package'
                withEnv(["PATH=/usr/local/bin:$PATH"]){
                             sh 'docker run -t -v packages:/var/lib/docker/volumes/packages/_data u16_build /bin/bash /var/lib/docker/volumes/packages/_data/ubuntu16/deploy.sh'
                }
            }
        }

    }
}


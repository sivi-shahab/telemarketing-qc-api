// GANTI SEBELUM DIPAKAI: REGISTRY (+ credentialsId 'gitlab-registry' di Jenkins).
pipeline {
  agent any

  environment {
    IMAGE    = "qc-api"
    REGISTRY = "registry.gitlab.<domain>/<group>"
    TAG      = "${env.GIT_COMMIT.take(8)}"
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
        // Wajib: tanpa ini folder core/ kosong dan build pasti gagal.
        sh 'git submodule update --init --recursive'
      }
    }

    stage('Test') {
      steps {
        sh '''
          python3 -m venv .venv
          . .venv/bin/activate
          pip install --upgrade pip
          pip install -r core/requirements.txt -r api/requirements.txt pytest
          PYTHONPATH=.:core pytest tests -q
        '''
      }
    }

    stage('No Worker Import') {
      // API hanya mengirim task by name; meng-import worker akan gagal di image.
      steps {
        sh '! grep -rn --include=*.py -E "^[[:space:]]*(from|import)[[:space:]]+worker\\b" api scripts tests'
      }
    }

    stage('Build') {
      steps {
        sh "docker build -f api/Dockerfile -t ${REGISTRY}/${IMAGE}:${TAG} -t ${REGISTRY}/${IMAGE}:latest ."
      }
    }

    stage('Push') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'gitlab-registry',
                                          usernameVariable: 'U', passwordVariable: 'P')]) {
          sh '''
            echo "$P" | docker login ${REGISTRY} -u "$U" --password-stdin
            docker push ${REGISTRY}/${IMAGE}:${TAG}
            docker push ${REGISTRY}/${IMAGE}:latest
          '''
        }
      }
    }

    stage('Deploy') {
      when { branch 'main' }
      steps {
        // Migrasi Alembic jalan otomatis di CMD container (alembic upgrade head
        // && uvicorn ...). Worker BARU boleh dideploy setelah stage ini hijau
        // kalau rilisnya mengandung perubahan skema.
        sh 'docker compose up -d --no-deps api'
      }
    }
  }
}

output "ansible_inventory" {
  description = "Run terraform output -json ansible_inventory > inventory.json"
  value = {
    all = {
      children = {
        lab_workers = {
          hosts = {
            lab_worker = {
              ansible_host               = aws_instance.worker.public_ip
              ansible_user               = "ubuntu"
              ansible_python_interpreter = "/usr/bin/python3"
            }
          }
        }
      }
    }
  }
}

output "worker_instance_id" {
  value = aws_instance.worker.id
}

output "instance_type" {
  value = aws_instance.worker.instance_type
}

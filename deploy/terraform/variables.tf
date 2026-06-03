variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "dropbox-to-gdrive"
}

variable "max_vcpus" {
  type    = number
  default = 4
}

variable "job_vcpu" {
  type    = number
  default = 1
}

variable "job_memory_mb" {
  type    = number
  default = 4096
}

variable "gdrive_root_folder_name" {
  type    = string
  default = "Dropbox Migration"
}

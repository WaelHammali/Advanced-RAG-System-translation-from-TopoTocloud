variable "region" {
  type        = string
  description = "AWS region; instance availability and pricing vary by region."
}

variable "lab_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,23}$", var.lab_name))
    error_message = "Use a lowercase lab name of 1-24 letters, digits or hyphens."
  }
}

variable "instance_type" {
  type        = string
  default     = "t4g.nano"
  description = "Smallest supported ARM worker; increase for larger labs."
  validation {
    condition     = contains(["t4g.nano", "t4g.micro", "t4g.small", "t4g.medium", "t4g.large", "t4g.xlarge", "t4g.2xlarge"], var.instance_type)
    error_message = "This backend uses ARM64 Ubuntu and supports the T4g family."
  }
}

variable "root_volume_gib" {
  type    = number
  default = 8
  validation {
    condition     = var.root_volume_gib >= 8 && var.root_volume_gib <= 100 && floor(var.root_volume_gib) == var.root_volume_gib
    error_message = "Choose 8-100 GiB for the educational worker."
  }
}

variable "ssh_admin_cidr" {
  type        = string
  description = "Your public IPv4 /32, allowed to SSH to the worker. No open SSH default."
  validation {
    condition     = can(cidrnetmask(var.ssh_admin_cidr)) && can(regex("/32$", var.ssh_admin_cidr))
    error_message = "Supply your public IPv4 address with /32."
  }
}

variable "ssh_public_key" {
  type        = string
  description = "Public SSH key only; supply the private key directly to Ansible."
  validation {
    condition     = can(regex("^ssh-(ed25519|rsa) ", var.ssh_public_key))
    error_message = "Provide an OpenSSH ed25519 or RSA public key."
  }
}

variable "use_spot" {
  type        = bool
  default     = false
  description = "Optional interruptible Spot worker. Prices and availability vary."
}

variable "ami_id" {
  type        = string
  default     = null
  nullable    = true
  description = "Optional pinned Ubuntu 24.04 ARM64 AMI; otherwise resolve Canonical's public SSM parameter."
}

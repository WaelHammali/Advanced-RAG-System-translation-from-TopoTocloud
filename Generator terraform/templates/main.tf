# One management worker. Lab prefixes are never installed in AWS route tables.
data "aws_ssm_parameter" "ubuntu" {
  count = var.ami_id == null ? 1 : 0
  name  = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
}

resource "aws_vpc" "management" {
  cidr_block           = "172.31.240.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.lab_name}-management" }
}

resource "aws_subnet" "management" {
  vpc_id                  = aws_vpc.management.id
  cidr_block              = "172.31.240.0/28"
  map_public_ip_on_launch = false
}

resource "aws_internet_gateway" "management" {
  vpc_id = aws_vpc.management.id
}

resource "aws_route_table" "management" {
  vpc_id = aws_vpc.management.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.management.id
  }
}

resource "aws_route_table_association" "management" {
  subnet_id      = aws_subnet.management.id
  route_table_id = aws_route_table.management.id
}

resource "aws_security_group" "worker" {
  name_prefix = "${var.lab_name}-"
  description = "Management SSH and package downloads; no lab service exposure"
  vpc_id      = aws_vpc.management.id
  ingress {
    description = "Administrator SSH"
    protocol    = "tcp"
    from_port   = 22
    to_port     = 22
    cidr_blocks = [var.ssh_admin_cidr]
  }
  egress {
    description = "HTTPS package and container downloads"
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "Distribution package mirrors"
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_key_pair" "worker" {
  key_name_prefix = "${var.lab_name}-"
  public_key      = var.ssh_public_key
}

resource "aws_instance" "worker" {
  ami                         = var.ami_id != null ? var.ami_id : data.aws_ssm_parameter.ubuntu[0].value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.management.id
  vpc_security_group_ids      = [aws_security_group.worker.id]
  key_name                    = aws_key_pair.worker.key_name
  associate_public_ip_address = true
  monitoring                  = false
  credit_specification {
    cpu_credits = "standard"
  }
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit  = 1
  }
  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gib
    encrypted             = true
    delete_on_termination = true
  }
  dynamic "instance_market_options" {
    for_each = var.use_spot ? [true] : []
    content {
      market_type = "spot"
      spot_options {
        spot_instance_type             = "one-time"
        instance_interruption_behavior = "terminate"
      }
    }
  }
  # Small educational machines can use disk-backed swap during installation.
  user_data = <<-CLOUDINIT
    #cloud-config
    swap:
      filename: /swapfile
      size: 1073741824
      maxsize: 1073741824
  CLOUDINIT
  tags = { Name = "${var.lab_name}-worker" }
  depends_on = [aws_route_table_association.management]
}

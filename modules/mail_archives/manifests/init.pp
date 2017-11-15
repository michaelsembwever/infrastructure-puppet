#/etc/puppet/modules/mail_archives/manifests.init.pp

class mail_archives (

  $username   = 'modmbox',
  $groupname  = 'modmbox',
  $shell      = '/bin/bash',

  # override below in yaml
  $parent_dir,

  $required_packages = ['apache2-dev' , 'autotools-dev' , 'autoconf' , 'libapr1' , 'libapr1-dev' , 'libaprutil1' , 'libaprutil1-dev' , 'scons'],
){

# install required packages:
  package {
    $required_packages:
      ensure => 'present',
  }

  $install_dir = "${parent_dir}/mail-archives"

  group {
    $groupname:
      ensure => present,
      system => true,
  }->

  user {
    $username:
      ensure     => present,
      home       => "/home/${username}",
      system     => true,
      managehome => true,
      name       => $username,
      shell      => $shell,
      gid        => $groupname,
      require    => Group[$groupname],
  }

  file {
    $install_dir:
      ensure => directory,
      owner  => $username,
      group  => 'root';
    "${install_dir}/raw":
      ensure => directory,
      mode   => '0755',
      owner  => $username,
      group  => 'root';
    "/home/${username}/scripts/":
      ensure => 'directory',
      mode   => '0755';

# required scripts for cron jobs

    "/home/${username}/scripts/mbox-raw-rsync.sh":
      ensure  => present,
      require => User[$username],
      owner   => $username,
      group   => $groupname,
      mode    => '0755',
      source  => 'puppet:///modules/mail_archives/scripts/mbox-raw-rsync.sh';

# symlink for apxs as SConstruct points to wrong dir

    '/usr/local/bin/apxs':
    ensure => link,
    target => '/usr/bin/apxs';

  }

# cron jobs

  cron {
    'public-mbox-rsync-raw':
      user        => $username,
      minute      => '42',
      command     => "/home/${username}/scripts/mbox-raw-rsync.sh",
      environment => "PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin\nSHELL=/bin/sh", # lint:ignore:double_quoted_strings
      require     => User[$username];
  }

}

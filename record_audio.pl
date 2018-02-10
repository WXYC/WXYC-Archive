#!/usr/bin/env perl

use Getopt::Long;
use File::Spec::Functions;
use File::Basename;
use File::Path qw/make_path/;
use Time::localtime;
use DateTime;

my $target_directory = catfile('/media/wxycarchive/Elements/');

my $duration = 0;
my $debug = 0;

GetOptions ('l=i' => \$duration, "debug" => \$debug) or die;

die "Please specify a recording duration in seconds with -l" if $duration == 0;

###############################################################################
# Recording
###############################################################################

my $dt = DateTime->now();
$dt->set_time_zone("America/New_York");

#to ensure that the files sort correctly, I'm forcing the midnight (2400)
#recording to read 0000 for the time part of the file name
my $base_file_name;
if ($dt->hour_1() == 24) {
	$base_file_name =sprintf('%s%02d%02d', 
		$dt->day_abbr(), 
		0, 
		$dt->min());
} else {
	$base_file_name =sprintf('%s%02d%02d', 
		$dt->day_abbr(), 
		$dt->hour_1(), 
		$dt->min());
}



my $flac_out = catfile($target_directory,'recordings','flac',$base_file_name . ".flac");
my $mp3_out = catfile($target_directory,'recordings','mp3',$dt->year(), 
	sprintf('%02d',$dt->month),sprintf('%02d',$dt->day), 
	$base_file_name . ".mp3");

my $wav_out = catfile($target_directory,'temp_recording',$base_file_name . ".wav");
make_path(dirname($wav_out));
make_path(dirname($flac_out));
make_path(dirname($mp3_out));

my $command = "arecord -q -d $duration -f cd $wav_out";
if ($debug) {
	print "$command\n";
} else {
	system($command);
}

$command = "flac --totally-silent $wav_out -o $flac_out";
if ($debug) {
	print "$command\n";
} else {
	system($command);
}

$command = "lame -V0 --quiet $wav_out $mp3_out";
if ($debug) {
	print "$command\n";
} else {
	system($command);
}

unlink("$wav_out");

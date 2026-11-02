本工程为AFC03的fpga工程，实现imx415摄像头接收，mipi发送到rk3576
rk3576端需要烧写对应的boot.img固件。
烧写bit后，使用gst命令查看显示
 gst-launch-1.0 v4l2src device=/dev/video22  ! kmssink
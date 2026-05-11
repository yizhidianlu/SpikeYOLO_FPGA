# hw/vivado/constraints/zybo_z7_20.xdc
# ZYBO Z7-20 master constraint file (subset).
# Derived from Digilent's official master XDC v1.4 — only the pins we use are
# uncommented. The full file lives at:
#   https://github.com/Digilent/Zybo-Z7-20/blob/master/Resources/XDC/Zybo-Z7-Master.xdc
#
# Keep edits minimal: add what we need, leave the rest commented for easy
# reactivation when the BD grows.

##Clock signal (125 MHz)
set_property -dict { PACKAGE_PIN K17   IOSTANDARD LVCMOS33 } [get_ports { sys_clk }];
create_clock -add -name sys_clk_pin -period 8.00 -waveform {0 4} [get_ports { sys_clk }];

##Switches (4 user)
set_property -dict { PACKAGE_PIN G15   IOSTANDARD LVCMOS33 } [get_ports { sw[0] }];
set_property -dict { PACKAGE_PIN P15   IOSTANDARD LVCMOS33 } [get_ports { sw[1] }];
set_property -dict { PACKAGE_PIN W13   IOSTANDARD LVCMOS33 } [get_ports { sw[2] }];
set_property -dict { PACKAGE_PIN T16   IOSTANDARD LVCMOS33 } [get_ports { sw[3] }];

##LEDs (4 user)
set_property -dict { PACKAGE_PIN M14   IOSTANDARD LVCMOS33 } [get_ports { led[0] }];
set_property -dict { PACKAGE_PIN M15   IOSTANDARD LVCMOS33 } [get_ports { led[1] }];
set_property -dict { PACKAGE_PIN G14   IOSTANDARD LVCMOS33 } [get_ports { led[2] }];
set_property -dict { PACKAGE_PIN D18   IOSTANDARD LVCMOS33 } [get_ports { led[3] }];

##HDMI TX (connector J11 — HDMI output)
set_property -dict { PACKAGE_PIN H17   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_clk_p }];
set_property -dict { PACKAGE_PIN H18   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_clk_n }];
set_property -dict { PACKAGE_PIN D19   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_data_p[0] }];
set_property -dict { PACKAGE_PIN D20   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_data_n[0] }];
set_property -dict { PACKAGE_PIN C20   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_data_p[1] }];
set_property -dict { PACKAGE_PIN B20   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_data_n[1] }];
set_property -dict { PACKAGE_PIN B19   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_data_p[2] }];
set_property -dict { PACKAGE_PIN A20   IOSTANDARD TMDS_33 } [get_ports { hdmi_tx_data_n[2] }];

##HDMI TX I2C / hot-plug-detect
set_property -dict { PACKAGE_PIN E18   IOSTANDARD LVCMOS33 } [get_ports { hdmi_tx_hpd }];
set_property -dict { PACKAGE_PIN G17   IOSTANDARD LVCMOS33 } [get_ports { hdmi_tx_ddc_sda }];
set_property -dict { PACKAGE_PIN G18   IOSTANDARD LVCMOS33 } [get_ports { hdmi_tx_ddc_scl }];

##USB OTG (host mode used for UVC camera)
##NOTE: USB PHY is managed by the PS via MIO; nothing to constrain in PL.

##Pcam MIPI (camera connector J5) — pinning kept for future R5 fallback
#set_property -dict { PACKAGE_PIN V13   IOSTANDARD HSUL_12 } [get_ports { dphy_clk_lp_n }];
#set_property -dict { PACKAGE_PIN W13   IOSTANDARD HSUL_12 } [get_ports { dphy_clk_lp_p }];

##Pmod headers (debug) — left commented; uncomment to expose GPIO for ILA probes
#set_property -dict { PACKAGE_PIN V8    IOSTANDARD LVCMOS33 } [get_ports { ja[0] }];

##Bitstream generation settings
set_property BITSTREAM.CONFIG.UNUSEDPIN PULLUP        [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE          [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4          [current_design]

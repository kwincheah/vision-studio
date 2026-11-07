<?xml version='1.0' encoding='utf-8'?>
<ApexSolution version="4.3" name="Precision_Measurement_Demo" active_flow="Precision_Measurement_Solution" trigger_flow="Precision_Measurement_Solution">
  <GlobalVariables>
    <Variable name="g_CountOK" type="int">0</Variable>
    <Variable name="g_CountNG" type="int">0</Variable>
    <Variable name="g_LotNumber" type="str">LOT-2026-A1</Variable>
    <Variable name="g_TriggerEnable" type="bool">true</Variable>
  </GlobalVariables>
  <Flows>
    <ApexFlow version="4.3" name="Precision_Measurement_Solution">
      <Properties>
        <Property name="enabled" type="bool">true</Property>
        <Property name="run_interval_ms" type="float">50.0</Property>
        <Property name="stop_on_ng" type="bool">false</Property>
        <Property name="flow_timeout_ms" type="float">5000.0</Property>
        <Property name="execution_count" type="int">0</Property>
      </Properties>
      <Nodes>
        <Node instance_id="node_source" tool_name="Image Source" name="01_Acquisition" category="Acquisition" enabled="true">
          <Parameters>
            <Parameter name="source_type" type="str">Synthetic</Parameter>
            <Parameter name="file_path" type="str">apex_vision/samples/pcb_sample.png</Parameter>
            <Parameter name="pattern_type" type="str">Circles &amp; Holes</Parameter>
            <Parameter name="color_mode" type="str">BGR</Parameter>
            <Parameter name="camera_device" type="str">mvs_gige_0</Parameter>
            <Parameter name="camera_index" type="int">0</Parameter>
            <Parameter name="exposure_time_us" type="float">20000.0</Parameter>
            <Parameter name="gain" type="float">1.0</Parameter>
            <Parameter name="trigger_mode" type="str">Continuous</Parameter>
            <Parameter name="mvs_config_file" type="str" />
            <Parameter name="mvs_trigger_source" type="str">Software</Parameter>
            <Parameter name="stream_url" type="str">rtsp://192.168.1.64:554/ch1/main</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_circle1" tool_name="Circle Search" name="02_InnerHoleFit" category="Location" enabled="true">
          <Parameters>
            <Parameter name="center_x" type="int">680</Parameter>
            <Parameter name="center_y" type="int">480</Parameter>
            <Parameter name="min_radius" type="int">15</Parameter>
            <Parameter name="max_radius" type="int">80</Parameter>
            <Parameter name="caliper_rays" type="int">32</Parameter>
            <Parameter name="edge_polarity" type="str">Any</Parameter>
            <Parameter name="edge_type" type="str">Strongest Edge</Parameter>
            <Parameter name="edge_threshold" type="float">25.0</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_p2p" tool_name="P2P Measure" name="03_HoleDistance" category="Measurement" enabled="true">
          <Parameters>
            <Parameter name="scale_factor" type="float">1.0</Parameter>
            <Parameter name="default_p1" type="json">[150, 150]</Parameter>
            <Parameter name="default_p2" type="json">[350, 150]</Parameter>
            <Parameter name="min_distance" type="float">0.0</Parameter>
            <Parameter name="max_distance" type="float">1000.0</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_intensity" tool_name="Intensity Measure" name="04_IlluminationCheck" category="Measurement" enabled="true">
          <Parameters>
            <Parameter name="roi" type="json">[200, 200, 200, 150]</Parameter>
            <Parameter name="min_mean" type="float">20.0</Parameter>
            <Parameter name="max_mean" type="float">240.0</Parameter>
          </Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="node_source" from_port="Image" to_node="node_circle1" to_port="Image" />
        <Connection from_node="node_source" from_port="Image" to_node="node_intensity" to_port="Image" />
      </Connections>
    </ApexFlow>
  </Flows>
</ApexSolution>
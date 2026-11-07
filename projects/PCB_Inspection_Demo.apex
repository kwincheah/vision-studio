<?xml version='1.0' encoding='utf-8'?>
<ApexSolution version="4.3" name="PCB_Inspection_Demo" active_flow="PCB_AOI_Solution" trigger_flow="PCB_AOI_Solution">
  <GlobalVariables>
    <Variable name="g_CountOK" type="int">0</Variable>
    <Variable name="g_CountNG" type="int">0</Variable>
    <Variable name="g_LotNumber" type="str">LOT-2026-A1</Variable>
    <Variable name="g_TriggerEnable" type="bool">true</Variable>
  </GlobalVariables>
  <Flows>
    <ApexFlow version="4.3" name="PCB_AOI_Solution">
      <Properties>
        <Property name="enabled" type="bool">true</Property>
        <Property name="run_interval_ms" type="float">50.0</Property>
        <Property name="stop_on_ng" type="bool">false</Property>
        <Property name="flow_timeout_ms" type="float">5000.0</Property>
        <Property name="execution_count" type="int">26</Property>
      </Properties>
      <Nodes>
        <Node instance_id="node_source" tool_name="Image Source" name="01_ImageAcquisition" category="Acquisition" enabled="true">
          <Parameters>
            <Parameter name="source_type" type="str">Synthetic</Parameter>
            <Parameter name="file_path" type="str">apex_vision/samples/pcb_sample.png</Parameter>
            <Parameter name="pattern_type" type="str">PCB Inspection</Parameter>
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
        <Node instance_id="node_template" tool_name="Template Match" name="02_IC_Alignment" category="Location" enabled="true">
          <Parameters>
            <Parameter name="min_score" type="float">0.7</Parameter>
            <Parameter name="template_roi" type="json">[260, 240, 180, 120]</Parameter>
            <Parameter name="start_angle" type="float">-15.0</Parameter>
            <Parameter name="end_angle" type="float">15.0</Parameter>
            <Parameter name="angle_step" type="float">2.0</Parameter>
            <Parameter name="max_matches" type="int">1</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_circle" tool_name="Circle Search" name="03_MountingHole" category="Location" enabled="true">
          <Parameters>
            <Parameter name="center_x" type="int">680</Parameter>
            <Parameter name="center_y" type="int">480</Parameter>
            <Parameter name="min_radius" type="int">25</Parameter>
            <Parameter name="max_radius" type="int">60</Parameter>
            <Parameter name="caliper_rays" type="int">32</Parameter>
            <Parameter name="edge_polarity" type="str">Any</Parameter>
            <Parameter name="edge_type" type="str">Strongest Edge</Parameter>
            <Parameter name="edge_threshold" type="float">25.0</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_caliper" tool_name="Caliper" name="04_TraceWidthCaliper" category="Location" enabled="true">
          <Parameters>
            <Parameter name="line_p1" type="json">[50, 150]</Parameter>
            <Parameter name="line_p2" type="json">[450, 150]</Parameter>
            <Parameter name="edge_threshold" type="float">25.0</Parameter>
            <Parameter name="polarity" type="str">Any</Parameter>
            <Parameter name="caliper_mode" type="str">Edge Pair</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_defect" tool_name="Defect Detection" name="05_SurfaceScratchCheck" category="Defect Detection" enabled="true">
          <Parameters>
            <Parameter name="roi" type="json">[260, 240, 180, 120]</Parameter>
            <Parameter name="defect_type" type="str">Dark / Scratch</Parameter>
            <Parameter name="sensitivity" type="int">30</Parameter>
            <Parameter name="min_defect_area" type="int">10</Parameter>
            <Parameter name="max_defect_area" type="int">500</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_branch" tool_name="Condition Branch" name="06_QualityJudge" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="operator" type="str">&lt;=</Parameter>
            <Parameter name="threshold_low" type="float">0.0</Parameter>
            <Parameter name="threshold_high" type="float">150.0</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_tcp" tool_name="TCP Send" name="07_SendToPLC" category="Communication" enabled="true">
          <Parameters>
            <Parameter name="mode" type="str">Simulation (Loopback Log)</Parameter>
            <Parameter name="server_ip" type="str">127.0.0.1</Parameter>
            <Parameter name="server_port" type="int">8080</Parameter>
            <Parameter name="prefix" type="str">APEX_RES,</Parameter>
            <Parameter name="suffix" type="str">\r\n</Parameter>
            <Parameter name="format" type="str">CSV</Parameter>
            <Parameter name="connect_timeout_ms" type="int">500</Parameter>
          </Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="node_source" from_port="Image" to_node="node_template" to_port="Image" />
        <Connection from_node="node_source" from_port="Image" to_node="node_circle" to_port="Image" />
        <Connection from_node="node_source" from_port="Image" to_node="node_caliper" to_port="Image" />
        <Connection from_node="node_source" from_port="Image" to_node="node_defect" to_port="Image" />
        <Connection from_node="node_defect" from_port="Defect_Count" to_node="node_branch" to_port="Val_In" />
        <Connection from_node="node_branch" from_port="Status" to_node="node_tcp" to_port="Data" />
      </Connections>
      <Layout>
        <Position node="node_source" x="50.0" y="50.0" />
        <Position node="node_template" x="310.0" y="50.0" />
        <Position node="node_circle" x="310.0" y="200.0" />
        <Position node="node_caliper" x="310.0" y="350.0" />
        <Position node="node_defect" x="310.0" y="500.0" />
        <Position node="node_branch" x="570.0" y="50.0" />
        <Position node="node_tcp" x="830.0" y="50.0" />
      </Layout>
    </ApexFlow>
  </Flows>
</ApexSolution>
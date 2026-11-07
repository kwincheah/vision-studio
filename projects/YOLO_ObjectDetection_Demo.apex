<?xml version='1.0' encoding='utf-8'?>
<ApexSolution version="4.3" name="YOLO_ObjectDetection_Demo" active_flow="YOLO_Detection_Solution" trigger_flow="YOLO_Detection_Solution">
  <GlobalVariables>
    <Variable name="g_CountOK" type="int">0</Variable>
    <Variable name="g_CountNG" type="int">0</Variable>
    <Variable name="g_LotNumber" type="str">LOT-2026-A1</Variable>
    <Variable name="g_TriggerEnable" type="bool">true</Variable>
  </GlobalVariables>
  <Flows>
    <ApexFlow version="4.3" name="YOLO_Detection_Solution">
      <Properties>
        <Property name="enabled" type="bool">true</Property>
        <Property name="run_interval_ms" type="float">50.0</Property>
        <Property name="stop_on_ng" type="bool">false</Property>
        <Property name="flow_timeout_ms" type="float">5000.0</Property>
        <Property name="execution_count" type="int">1</Property>
      </Properties>
      <Nodes>
        <Node instance_id="node_source" tool_name="Image Source" name="01_Acquisition" category="Acquisition" enabled="true">
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
        <Node instance_id="node_yolo" tool_name="Object Detection" name="02_YOLOv11_Detector" category="Recognition" enabled="true">
          <Parameters>
            <Parameter name="model_path" type="str">yolo11n.pt</Parameter>
            <Parameter name="confidence" type="float">0.25</Parameter>
            <Parameter name="iou" type="float">0.45</Parameter>
            <Parameter name="classes" type="str">all</Parameter>
            <Parameter name="device" type="str">cpu</Parameter>
            <Parameter name="max_detections" type="int">100</Parameter>
          </Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="node_source" from_port="Image" to_node="node_yolo" to_port="Image" />
      </Connections>
      <Layout>
        <Position node="node_source" x="50.0" y="50.0" />
        <Position node="node_yolo" x="488.0" y="63.0" />
      </Layout>
    </ApexFlow>
  </Flows>
</ApexSolution>
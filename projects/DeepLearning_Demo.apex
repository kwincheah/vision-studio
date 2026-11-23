<?xml version='1.0' encoding='utf-8'?>
<ApexSolution version="4.3" name="DeepLearning_Demo" active_flow="DeepLearning_Flow" trigger_flow="DeepLearning_Flow">
  <GlobalVariables>
    <Variable name="g_CountOK" type="int">0</Variable>
    <Variable name="g_CountNG" type="int">0</Variable>
    <Variable name="g_LotNumber" type="str">LOT-2026-A1</Variable>
    <Variable name="g_TriggerEnable" type="bool">true</Variable>
  </GlobalVariables>
  <Flows>
    <ApexFlow version="4.3" name="DeepLearning_Flow">
      <Properties>
        <Property name="enabled" type="bool">true</Property>
        <Property name="run_interval_ms" type="float">50.0</Property>
        <Property name="stop_on_ng" type="bool">false</Property>
        <Property name="flow_timeout_ms" type="float">5000.0</Property>
        <Property name="execution_count" type="int">0</Property>
      </Properties>
      <Nodes>
        <Node instance_id="node_source" tool_name="Image Source" name="01_MetalSurface" category="Acquisition" enabled="true">
          <Parameters>
            <Parameter name="source_type" type="str">Synthetic</Parameter>
            <Parameter name="file_path" type="str">C:\Users\winch\Downloads\VMClone\apex_vision\samples\pcb_sample.png</Parameter>
            <Parameter name="pattern_type" type="str">Metal Surface (demo)</Parameter>
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
        <Node instance_id="node_classify" tool_name="DL Classify" name="02_Classify_GoodOrDefective" category="Deep Learning" enabled="true">
          <Parameters>
            <Parameter name="model_path" type="str">demo_defect_classifier.onnx</Parameter>
            <Parameter name="backend" type="str">Auto</Parameter>
            <Parameter name="device" type="str">cpu</Parameter>
            <Parameter name="labels" type="str" />
            <Parameter name="input_width" type="int">0</Parameter>
            <Parameter name="input_height" type="int">0</Parameter>
            <Parameter name="resize" type="str">Auto</Parameter>
            <Parameter name="normalize" type="str">Auto</Parameter>
            <Parameter name="rgb_input" type="bool">true</Parameter>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
            <Parameter name="top_k" type="int">3</Parameter>
            <Parameter name="ok_labels" type="str">good</Parameter>
            <Parameter name="min_confidence" type="float">0.5</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_segment" tool_name="DL Segment" name="03_Segment_DefectPixels" category="Deep Learning" enabled="true">
          <Parameters>
            <Parameter name="model_path" type="str">demo_defect_segmenter.onnx</Parameter>
            <Parameter name="backend" type="str">Auto</Parameter>
            <Parameter name="device" type="str">cpu</Parameter>
            <Parameter name="labels" type="str" />
            <Parameter name="input_width" type="int">0</Parameter>
            <Parameter name="input_height" type="int">0</Parameter>
            <Parameter name="resize" type="str">Auto</Parameter>
            <Parameter name="normalize" type="str">Auto</Parameter>
            <Parameter name="rgb_input" type="bool">true</Parameter>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
            <Parameter name="defect_classes" type="str" />
            <Parameter name="background_class" type="int">0</Parameter>
            <Parameter name="threshold" type="float">0.5</Parameter>
            <Parameter name="min_area" type="int">40</Parameter>
            <Parameter name="max_defect_count" type="int">0</Parameter>
            <Parameter name="max_defect_ratio" type="float">100.0</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_anomaly" tool_name="DL Anomaly" name="04_Anomaly_NotLikeAGoodPart" category="Deep Learning" enabled="true">
          <Parameters>
            <Parameter name="model_path" type="str">demo_anomaly.onnx</Parameter>
            <Parameter name="backend" type="str">Auto</Parameter>
            <Parameter name="device" type="str">cpu</Parameter>
            <Parameter name="input_width" type="int">0</Parameter>
            <Parameter name="input_height" type="int">0</Parameter>
            <Parameter name="resize" type="str">Auto</Parameter>
            <Parameter name="normalize" type="str">Auto</Parameter>
            <Parameter name="rgb_input" type="bool">true</Parameter>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
            <Parameter name="output_type" type="str">Auto (from the model)</Parameter>
            <Parameter name="map_threshold" type="float">0.0</Parameter>
            <Parameter name="smoothing" type="float">2.0</Parameter>
            <Parameter name="min_area" type="int">40</Parameter>
            <Parameter name="max_defect_count" type="int">0</Parameter>
          </Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="node_source" from_port="Image" to_node="node_classify" to_port="Image" />
        <Connection from_node="node_source" from_port="Image" to_node="node_segment" to_port="Image" />
        <Connection from_node="node_source" from_port="Image" to_node="node_anomaly" to_port="Image" />
      </Connections>
      <Layout>
        <Position node="node_source" x="40.0" y="260.0" />
        <Position node="node_classify" x="380.0" y="40.0" />
        <Position node="node_segment" x="380.0" y="290.0" />
        <Position node="node_anomaly" x="380.0" y="540.0" />
      </Layout>
    </ApexFlow>
  </Flows>
</ApexSolution>
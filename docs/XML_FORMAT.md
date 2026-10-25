# Solution XML format

A solution can be saved and loaded as XML (`File > Save Solution As... > Vision Solution XML`,
or any path ending in `.xml`; `Open Solution` and the Start page read it back). It carries
exactly what a `.vmp` JSON project carries, so the two are interchangeable.

```xml
<?xml version='1.0' encoding='utf-8'?>
<ApexSolution version="4.3" name="MySolution" active_flow="Flow1" trigger_flow="Flow1">
  <GlobalVariables>
    <Variable name="g_CountOK" type="int">0</Variable>
    <Variable name="g_Lot" type="str">LOT-1</Variable>
  </GlobalVariables>
  <GlobalScript type="str">def process(context): ...</GlobalScript>      <!-- optional -->
  <Flows>
    <ApexFlow version="4.3" name="Flow1">
      <Properties>
        <Property name="enabled" type="bool">true</Property>
        <Property name="run_interval_ms" type="float">50.0</Property>
        <Property name="stop_on_ng" type="bool">false</Property>
        <Property name="flow_timeout_ms" type="float">5000.0</Property>
        <Property name="execution_count" type="int">0</Property>
      </Properties>
      <Nodes>
        <Node instance_id="src" tool_name="Image Source" name="01_Acquisition" category="Acquisition" enabled="true">
          <Parameters>
            <Parameter name="source_type" type="str">Synthetic</Parameter>
            <Parameter name="roi" type="json">[80, 490, 300, 60]</Parameter>
          </Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="src" from_port="Image" to_node="thr" to_port="Image"/>
      </Connections>
      <Layout>                                                            <!-- optional -->
        <Position node="src" x="50.0" y="50.0"/>
      </Layout>
    </ApexFlow>
  </Flows>
</ApexSolution>
```

* A document whose root is a single `<ApexFlow>` (the *Export Flow as XML* output) also
  opens, as a one-flow solution.
* Value `type` is one of `str`, `int`, `float`, `bool`, `json` (lists / dicts), `null`, or
  `jsonstr` (a JSON string literal, used for text XML cannot carry verbatim such as control
  characters or carriage returns).
* `tool_name` and port names are those shown in the Tool Box / on the module cards. A tool that
  is not installed loads as a placeholder module that keeps its parameters.
* `<Layout>` is presentation only; when it is absent the flow is auto-arranged.
* DTD / entity declarations are rejected on load.

Files saved by earlier versions use the root names `<VisionMasterSolution>` and `<VisionMasterFlow>`. They still open, and are written back with the new names the next time they are saved.

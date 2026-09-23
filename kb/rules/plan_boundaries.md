## [PLAN-001] Keep AWS hosting and source network configuration in one plan
Rule-ID: PLAN-001
Kind: rule
Mode: behavioral_lab
Phase: topology
Status: target_specification
Keywords: AWS, JSON, cloud plan, configuration, source graph, resource mapping
Applies: Translating a ready architecture into an AWS JSON plan.
Required: Follow required_cloud_plan exactly: AWS resources, device_mapping, per-cable veth endpoints, configuration_targets and empty initial route/protocol/service lists. Educational hosting is selected by Python from a reviewed bounded catalog. Later configuration belongs to the external agent/generator.
Forbidden: Do not output deployment files, executable commands, provider-specific playbooks or a second independently inferred source graph.
Expected: One internally consistent AWS plan plus unchanged source architecture and rule provenance. Resource references are symbolic until an external implementation exists.
Verify: Python checks complete source coverage, exact addressing, stable runtime targets and the selected hosting profile. Record unresolved management/bootstrap and capacity dependencies.
Sources: PROJECT
Related: INPUT-001, PLAN-002

## [PLAN-002] A plan is not deployment or behavioral verification
Rule-ID: PLAN-002
Kind: rule
Mode: all
Phase: topology
Status: target_specification
Keywords: AWS, plan, provisioning, readiness, verification, status
Applies: Describing the expected behavior of a translated architecture.
Required: Separate configuration-based predictions from observations. This application only returns JSON; provisioning, runtime readiness and packet tests require external tools and evidence.
Forbidden: Do not claim a working network from a valid JSON plan, created AWS resources or printed neighbor output.
Expected: A negative lab may conform while ping fails. Unmeasured outcomes remain unverified, never reported as observed success.
Verify: Require recorded runtime measurements for any claim of completed network behavior.
Sources: PROJECT
Related: CORE-003, VERIFY-001

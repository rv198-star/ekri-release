# Mercury CI Service

Mercury is a small software delivery service that accepts source revisions, builds immutable artifacts, executes verification, and submits a deployment candidate to an independent deployment admission decision.

The source-control boundary owns source revision identity. The build worker owns build execution and the resulting build artifact. The test runner owns verification results. Deployment approval is intentionally not implied by build or test success.

The delivery chain is source revision -> build artifact -> test report -> deployment admission.

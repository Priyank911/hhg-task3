import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

const EvidenceRegistryModule = buildModule("EvidenceRegistryModule", (m) => {
  const defaultAttester = m.getAccount(0);
  const attester = m.getParameter("attester", defaultAttester);

  const registry = m.contract("EvidenceRegistry", [attester]);

  return { registry };
});

export default EvidenceRegistryModule;

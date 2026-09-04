import { expect } from "chai";
import { ethers } from "hardhat";

describe("EvidenceRegistry", function () {
  let registry: any;
  let owner: any;
  let otherAccount: any;
  const sampleHash = ethers.keccak256(ethers.toUtf8Bytes("sample_evidence_manifest_bytes"));
  const zeroHash = ethers.ZeroHash;

  beforeEach(async function () {
    [owner, otherAccount] = await ethers.getSigners();
    const EvidenceRegistry = await ethers.getContractFactory("EvidenceRegistry");
    registry = await EvidenceRegistry.deploy(owner.address);
    await registry.waitForDeployment();
  });

  describe("Deployment", function () {
    it("Should set the right attester", async function () {
      expect(await registry.attester()).to.equal(owner.address);
    });

    it("Should revert if deployed with zero address attester", async function () {
      const EvidenceRegistry = await ethers.getContractFactory("EvidenceRegistry");
      await expect(EvidenceRegistry.deploy(ethers.ZeroAddress)).to.be.revertedWithCustomError(
        registry,
        "InvalidAttester"
      );
    });
  });

  describe("Registration", function () {
    it("Should allow the authorized attester to register evidence", async function () {
      const tx = await registry.registerEvidence(sampleHash);
      const receipt = await tx.wait();

      expect(await registry.isRegistered(sampleHash)).to.be.true;

      const [submitter, registeredAt, blockNumber, exists] = await registry.getEvidence(sampleHash);
      expect(submitter).to.equal(owner.address);
      expect(exists).to.be.true;
      expect(blockNumber).to.equal(receipt.blockNumber);
      expect(registeredAt).to.be.gt(0);
    });

    it("Should emit EvidenceRegistered event with correct parameters", async function () {
      await expect(registry.registerEvidence(sampleHash))
        .to.emit(registry, "EvidenceRegistered")
        .withArgs(sampleHash, owner.address, (val: any) => val > 0, (val: any) => val > 0);
    });

    it("Should reject registration from unauthorized caller", async function () {
      await expect(
        registry.connect(otherAccount).registerEvidence(sampleHash)
      ).to.be.revertedWithCustomError(registry, "Unauthorized").withArgs(otherAccount.address);
    });

    it("Should reject zero hash registration", async function () {
      await expect(
        registry.registerEvidence(zeroHash)
      ).to.be.revertedWithCustomError(registry, "InvalidZeroHash");
    });

    it("Should reject duplicate registration of the same hash", async function () {
      await registry.registerEvidence(sampleHash);
      await expect(
        registry.registerEvidence(sampleHash)
      ).to.be.revertedWithCustomError(registry, "AlreadyRegistered").withArgs(sampleHash);
    });
  });

  describe("Queries", function () {
    it("Should return exists=false for unregistered hash", async function () {
      const unusedHash = ethers.keccak256(ethers.toUtf8Bytes("unregistered"));
      expect(await registry.isRegistered(unusedHash)).to.be.false;

      const [submitter, registeredAt, blockNumber, exists] = await registry.getEvidence(unusedHash);
      expect(exists).to.be.false;
      expect(submitter).to.equal(ethers.ZeroAddress);
      expect(registeredAt).to.equal(0);
      expect(blockNumber).to.equal(0);
    });
  });
});

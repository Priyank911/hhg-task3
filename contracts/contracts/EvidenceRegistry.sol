// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/**
 * @title EvidenceRegistry
 * @notice Cryptographic registry for immutable off-chain evidence digests (SHA-256 manifests).
 * @dev Stores 32-byte hashes committed by an authorized attester. Does not store raw data or PII.
 */
contract EvidenceRegistry {
    struct EvidenceRecord {
        address submitter;
        uint256 registeredAt;
        uint256 blockNumber;
        bool exists;
    }

    /// @notice Authorized attester account permitted to anchor evidence records.
    address public immutable attester;

    /// @notice Mapping from evidence hash (SHA-256) to its on-chain registration record.
    mapping(bytes32 => EvidenceRecord) private _records;

    /// @notice Emitted whenever a new unique evidence hash is registered.
    event EvidenceRegistered(
        bytes32 indexed evidenceHash,
        address indexed submitter,
        uint256 blockNumber,
        uint256 registeredAt
    );

    error Unauthorized(address caller);
    error InvalidZeroHash();
    error AlreadyRegistered(bytes32 evidenceHash);
    error InvalidAttester();

    modifier onlyAttester() {
        if (msg.sender != attester) {
            revert Unauthorized(msg.sender);
        }
        _;
    }

    /**
     * @param _attester Address of the authorized attester (defaults to deployer if address(0) is not provided).
     */
    constructor(address _attester) {
        if (_attester == address(0)) {
            revert InvalidAttester();
        }
        attester = _attester;
    }

    /**
     * @notice Registers a new 32-byte evidence hash.
     * @param evidenceHash The SHA-256 hash of the canonical RFC 8785 evidence manifest.
     */
    function registerEvidence(bytes32 evidenceHash) external onlyAttester {
        if (evidenceHash == bytes32(0)) {
            revert InvalidZeroHash();
        }
        if (_records[evidenceHash].exists) {
            revert AlreadyRegistered(evidenceHash);
        }

        _records[evidenceHash] = EvidenceRecord({
            submitter: msg.sender,
            registeredAt: block.timestamp,
            blockNumber: block.number,
            exists: true
        });

        emit EvidenceRegistered(
            evidenceHash,
            msg.sender,
            block.number,
            block.timestamp
        );
    }

    /**
     * @notice Checks whether an evidence hash has been registered.
     * @param evidenceHash The SHA-256 digest to query.
     * @return exists True if registered, false otherwise.
     */
    function isRegistered(bytes32 evidenceHash) external view returns (bool) {
        return _records[evidenceHash].exists;
    }

    /**
     * @notice Retrieves the full registration record for a given evidence hash.
     * @param evidenceHash The SHA-256 digest to query.
     */
    function getEvidence(bytes32 evidenceHash)
        external
        view
        returns (
            address submitter,
            uint256 registeredAt,
            uint256 blockNumber,
            bool exists
        )
    {
        EvidenceRecord memory rec = _records[evidenceHash];
        return (rec.submitter, rec.registeredAt, rec.blockNumber, rec.exists);
    }
}

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Tuple
from web3 import Web3
from web3.exceptions import ContractLogicError

from app.schemas import AttestationSidecar

EVIDENCE_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "_attester", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "evidenceHash", "type": "bytes32"}],
        "name": "AlreadyRegistered",
        "type": "error",
    },
    {"inputs": [], "name": "InvalidAttester", "type": "error"},
    {"inputs": [], "name": "InvalidZeroHash", "type": "error"},
    {
        "inputs": [{"internalType": "address", "name": "caller", "type": "address"}],
        "name": "Unauthorized",
        "type": "error",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "evidenceHash", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "submitter", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "blockNumber", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "registeredAt", "type": "uint256"},
        ],
        "name": "EvidenceRegistered",
        "type": "event",
    },
    {
        "inputs": [],
        "name": "attester",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "evidenceHash", "type": "bytes32"}],
        "name": "getEvidence",
        "outputs": [
            {"internalType": "address", "name": "submitter", "type": "address"},
            {"internalType": "uint256", "name": "registeredAt", "type": "uint256"},
            {"internalType": "uint256", "name": "blockNumber", "type": "uint256"},
            {"internalType": "bool", "name": "exists", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "evidenceHash", "type": "bytes32"}],
        "name": "isRegistered",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "evidenceHash", "type": "bytes32"}],
        "name": "registerEvidence",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class BlockchainError(Exception):
    pass


class BlockchainService:
    def __init__(
        self,
        rpc_url: str,
        chain_id: int,
        contract_address: Optional[str] = None,
        private_key: Optional[str] = None,
    ):
        self.rpc_url = rpc_url
        self.chain_id = chain_id
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.contract_address = Web3.to_checksum_address(contract_address) if contract_address else None
        self.private_key = private_key
        
        self.contract = None
        if self.contract_address:
            self.contract = self.w3.eth.contract(
                address=self.contract_address,
                abi=EVIDENCE_REGISTRY_ABI,
            )

    def is_connected(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    def get_authorized_attester(self) -> Optional[str]:
        if not self.contract:
            return None
        return self.contract.functions.attester().call()

    def is_hash_registered(self, evidence_hash_hex: str) -> bool:
        if not self.contract:
            raise BlockchainError("Contract address is not configured.")
        
        hash_bytes = Web3.to_bytes(hexstr=evidence_hash_hex)
        return self.contract.functions.isRegistered(hash_bytes).call()

    def get_evidence_record(self, evidence_hash_hex: str) -> dict[str, Any]:
        if not self.contract:
            raise BlockchainError("Contract address is not configured.")

        hash_bytes = Web3.to_bytes(hexstr=evidence_hash_hex)
        submitter, registered_at, block_num, exists = self.contract.functions.getEvidence(hash_bytes).call()
        return {
            "submitter": submitter,
            "registeredAt": registered_at,
            "blockNumber": block_num,
            "exists": exists,
        }

    def register_evidence_hash(self, evidence_hash_hex: str) -> AttestationSidecar:
        if not self.contract:
            raise BlockchainError("Contract address is not configured.")
        if not self.private_key:
            raise BlockchainError("Attester private key is required for blockchain registration.")

        account = self.w3.eth.account.from_key(self.private_key)
        attester_address = account.address

        # Convert hex string to 32 bytes
        hash_bytes = Web3.to_bytes(hexstr=evidence_hash_hex)

        # Check if already registered
        if self.contract.functions.isRegistered(hash_bytes).call():
            raise BlockchainError(f"Evidence hash {evidence_hash_hex} is already registered on-chain.")

        nonce = self.w3.eth.get_transaction_count(attester_address)
        gas_price = self.w3.eth.gas_price

        tx = self.contract.functions.registerEvidence(hash_bytes).build_transaction({
            "from": attester_address,
            "nonce": nonce,
            "gas": 200000,
            "gasPrice": gas_price,
            "chainId": self.chain_id,
        })

        signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30.0)
        if receipt["status"] != 1:
            raise BlockchainError(f"Transaction failed with status 0. TxHash: {tx_hash.hex()}")

        return AttestationSidecar(
            evidenceHash=evidence_hash_hex,
            chainId=str(self.chain_id),
            contractAddress=self.contract_address,
            transactionHash=tx_hash.hex(),
            blockNumber=str(receipt["blockNumber"]),
            registrant=attester_address,
            receiptStatus="success",
        )

    @staticmethod
    def save_attestation(attestation: AttestationSidecar, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(attestation.model_dump(), f, indent=2)

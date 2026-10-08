#!/usr/bin/env node
// Copyright (c) 2026 The REvoDesign Developers.
// Distributed under the terms of the GNU General Public License v3.0.
// SPDX-License-Identifier: GPL-3.0-only
//
// A second, genuinely independent MCP host for the REvoCompute MCP surface:
// the official *TypeScript* MCP SDK (@modelcontextprotocol/sdk), a different
// implementation, language, and transport stack from both the Python SDK the
// adapter is built on and the fastmcp host.
//
// It is launched by tests/mcp_independent_host.py as the `--typescript` half.

import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { Client } = require('@modelcontextprotocol/sdk/client/index.js');
const { StreamableHTTPClientTransport } = require('@modelcontextprotocol/sdk/client/streamableHttp.js');

const fixtures = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const url = process.argv[3];
const version = process.env.REVOCOMPUTE_TS_HOST_VERSION || 'unknown';

function structured(result) {
  if (result && result.structuredContent && typeof result.structuredContent === 'object') {
    return result.structuredContent;
  }
  const content = (result && result.content) || [];
  for (const block of content) {
    if (block && block.type === 'text' && block.text) {
      try {
        const parsed = JSON.parse(block.text);
        if (parsed && typeof parsed === 'object') return parsed;
      } catch (error) { /* not JSON: keep looking */ }
    }
  }
  return {};
}

function payloadOfError(error) {
  // The SDK raises on a transport/protocol error; a tool-declared failure
  // arrives as isError. Normalize both to one (isError, payload) shape.
  const match = /\{.*\}/s.exec(String(error && error.message ? error.message : error));
  if (match) {
    try { return { isError: true, payload: JSON.parse(match[0]) }; } catch (e) { /* fall through */ }
  }
  return { isError: true, payload: { message: String(error && error.message ? error.message : error) } };
}

async function call(client, name, args) {
  try {
    const result = await client.callTool({ name, arguments: args });
    return { isError: Boolean(result.isError), payload: structured(result) };
  } catch (error) {
    return payloadOfError(error);
  }
}

function isHex32(value) {
  return typeof value === 'string' && value.length === 32 && /^[0-9a-fA-F]+$/.test(value);
}

async function run(token) {
  const transport = new StreamableHTTPClientTransport(new URL(url), {
    requestInit: { headers: { Authorization: `Bearer ${token}` } },
  });
  // The SDK negotiates the protocol version during connect and hands the
  // server's choice to the transport; capture it so the receipt records the
  // negotiated version rather than the client's requested one.
  let negotiated = null;
  const original = transport.setProtocolVersion.bind(transport);
  transport.setProtocolVersion = (version) => {
    negotiated = version;
    original(version);
  };
  const client = new Client({ name: 'revocompute-independent-ts-host', version: '1.0.0' });
  await client.connect(transport);
  return { client, transport, negotiated };
}

const receipt = {
  host: 'mcp-typescript-sdk',
  host_version: version,
  host_protocol_library: `@modelcontextprotocol/sdk ${version}`,
  exact_head: process.env.REVOCOMPUTE_EXACT_HEAD || 'unknown',
  steps: {},
};

const { client, negotiated } = await run(fixtures.token);
receipt.protocol_version = negotiated;
const serverVersion = client.getServerVersion();
receipt.server = { name: serverVersion.name, version: serverVersion.version };

const tools = await client.listTools();
receipt.tools = tools.tools.map((t) => t.name).sort();
receipt.steps.list_tools = { error: false, count: tools.tools.length };

const resources = await client.listResources();
receipt.steps.list_resources = { error: false, uris: resources.resources.map((r) => String(r.uri)).sort() };

{
  const { isError, payload } = await call(client, 'discover_tasks', {});
  const catalog = payload.task_types || [];
  receipt.steps.discover_tasks = { error: isError, count: catalog.length, sample: catalog.length ? catalog[0].task_type : null };
  if (catalog.length) {
    const inspected = await call(client, 'inspect_task', { task_type: catalog[0].task_type });
    receipt.steps.inspect_task = {
      error: inspected.isError,
      task_type: inspected.payload.task_type,
      has_schema: Boolean(inspected.payload.parameter_schema),
    };
  }
}

const submissionInputs = [
  {
    role: fixtures.submit_role,
    filename: 'independent.fasta',
    content_base64: Buffer.from('>independent\nACDEFGHIKLMNPQRSTVWY\n').toString('base64'),
  },
];

{
  const preflight = await call(client, 'preflight_task', {
    task_type: fixtures.submit_task_type, params: {}, inputs: submissionInputs,
  });
  receipt.steps.preflight_task = {
    error: preflight.isError, valid: preflight.payload.valid, error_class: preflight.payload.error_class || null,
  };
}

let freshHandle = null;
{
  const submitted = await call(client, 'submit_task', {
    task_type: fixtures.submit_task_type, params: {}, inputs: submissionInputs,
  });
  freshHandle = submitted.payload.task_handle || null;
  receipt.steps.submit_task = {
    error: submitted.isError,
    error_class: submitted.payload.error_class || null,
    handle_returned: Boolean(freshHandle),
    handle_is_not_task_id: Boolean(freshHandle) && !isHex32(freshHandle),
  };
}

{
  const status = await call(client, 'get_task_status', { task_handle: fixtures.handle });
  receipt.steps.status_own_handle = { error: status.isError, status: status.payload.status };
}

{
  const results = await call(client, 'get_task_results', { task_handle: fixtures.handle });
  receipt.steps.results_own_handle = { error: results.isError, artifacts: (results.payload.artifacts || []).length };
}

{
  const artifact = await call(client, 'retrieve_artifact', { task_handle: fixtures.handle, artifact_path: 'output.txt' });
  const content = artifact.payload.content_base64;
  receipt.steps.retrieve_artifact = {
    error: artifact.isError,
    inline: artifact.payload.inline,
    bytes_ok: Boolean(content) && Buffer.from(content, 'base64').toString('utf-8') === 'independent-artifact\n',
  };
}

{
  const traversal = await call(client, 'retrieve_artifact', { task_handle: fixtures.handle, artifact_path: '../../etc/passwd' });
  receipt.steps.negative_traversal = { error: traversal.isError, error_class: traversal.payload.error_class || null };
}
{
  const missing = await call(client, 'retrieve_artifact', { task_handle: fixtures.handle, artifact_path: 'missing.txt' });
  receipt.steps.negative_missing_artifact = { error: missing.isError, error_class: missing.payload.error_class || null };
}
{
  const quarantined = await call(client, 'retrieve_artifact', {
    task_handle: fixtures.quarantine_handle, artifact_path: 'quarantined.txt',
  });
  receipt.steps.negative_quarantined_artifact = {
    error: quarantined.isError,
    error_class: quarantined.payload.error_class || null,
    detail: quarantined.payload.detail || null,
    content_base64: quarantined.payload.content_base64 || null,
  };
}
{
  const unknown = await call(client, 'submit_task', {
    task_type: 'definitely-not-a-task', params: {}, inputs: submissionInputs,
  });
  receipt.steps.negative_unknown_submit = { error: unknown.isError, error_class: unknown.payload.error_class || null };
}
{
  const invalid = await call(client, 'submit_task', {
    task_type: fixtures.submit_task_type,
    params: { definitely_not_a_parameter: 'x' },
    inputs: [{
      role: 'not-a-real-role',
      filename: 'x.fasta',
      content_base64: Buffer.from('>x\nACDEFGHIK\n').toString('base64'),
    }],
  });
  receipt.steps.negative_invalid_parameters = { error: invalid.isError, error_class: invalid.payload.error_class || null };
}
{
  const retry = await call(client, 'submit_task', {
    task_type: fixtures.submit_task_type, params: {}, inputs: submissionInputs,
  });
  const retryHandle = retry.payload.task_handle || null;
  receipt.steps.retry_submit = { error: retry.isError, fresh_handle: Boolean(retryHandle) && retryHandle !== freshHandle };
}
{
  const cancel = await call(client, 'cancel_task', { task_handle: fixtures.handle });
  receipt.steps.cancel_terminal_task = { error: cancel.isError, error_class: cancel.payload.error_class || null };
}
{
  const oversized = await call(client, 'retrieve_artifact', { task_handle: fixtures.big_handle, artifact_path: 'big.txt' });
  receipt.steps.negative_oversized_artifact = {
    error: oversized.isError,
    inline: oversized.payload.inline,
    content_base64: oversized.payload.content_base64 || null,
    leaks_task_id: JSON.stringify(oversized.payload).includes(fixtures.big_task_id),
  };
}
{
  const cross = await call(client, 'get_task_status', { task_handle: fixtures.foreign_handle });
  receipt.steps.negative_cross_user_handle = { error: cross.isError, error_class: cross.payload.error_class || null };
}

await client.close();

{
  const { client: otherClient } = await run(fixtures.other_token);
  const stolen = await call(otherClient, 'get_task_status', { task_handle: fixtures.handle });
  receipt.steps.negative_stolen_handle = { error: stolen.isError, error_class: stolen.payload.error_class || null };
  await otherClient.close();
}
{
  const transport = new StreamableHTTPClientTransport(new URL(url));
  const anonymousClient = new Client({ name: 'revocompute-independent-ts-host', version: '1.0.0' });
  await anonymousClient.connect(transport);
  const anonymous = await call(anonymousClient, 'discover_tools', {});
  receipt.steps.negative_anonymous = { error: anonymous.isError, error_class: anonymous.payload.error_class || null };
  await anonymousClient.close();
}
{
  const transport = new StreamableHTTPClientTransport(new URL(url), {
    requestInit: { headers: { Authorization: 'Bearer not-a-real-token' } },
  });
  const forgedClient = new Client({ name: 'revocompute-independent-ts-host', version: '1.0.0' });
  await forgedClient.connect(transport);
  const forged = await call(forgedClient, 'discover_tools', {});
  receipt.steps.negative_invalid_bearer = { error: forged.isError, error_class: forged.payload.error_class || null };
  await forgedClient.close();
}

process.stdout.write(JSON.stringify(receipt));

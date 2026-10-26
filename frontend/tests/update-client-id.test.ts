import assert from "node:assert/strict"
import test from "node:test"

import { createUpdateClientId } from "../src/lib/update-client-id.ts"

test("creates distinct update client IDs when HTTP origin has no randomUUID", () => {
  const httpCrypto = {
    getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
  }
  const first = createUpdateClientId(httpCrypto)
  const second = createUpdateClientId(httpCrypto)
  assert.match(first, /^[a-f0-9]{32}$/)
  assert.match(second, /^[a-f0-9]{32}$/)
  assert.notEqual(first, second)
})

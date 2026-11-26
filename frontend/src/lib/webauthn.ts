/**
 * Browser side of the approved-device boundary (backend/app/devices.py): turns the server's WebAuthn options into the
 * calls the browser understands and serialises the authenticator's answer back the way the server verifies it.
 * The private key never leaves the device's authenticator (Windows Hello / TPM, Touch ID, Android, security key).
 */

function b64urlToBuffer(s: string): ArrayBuffer {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function bufferToB64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function webauthnSupported(): boolean {
  return typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;
}

/** A credential object in the JSON shape the server expects (id, rawId, type, response, clientExtensionResults). */
export type CredentialJSON = Record<string, unknown>;

export async function createCredential(optionsJson: string): Promise<CredentialJSON> {
  const o = JSON.parse(optionsJson);
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...o,
    challenge: b64urlToBuffer(o.challenge),
    user: { ...o.user, id: b64urlToBuffer(o.user.id) },
    excludeCredentials: (o.excludeCredentials ?? []).map((c: { id: string; type: string; transports?: string[] }) => ({ ...c, id: b64urlToBuffer(c.id) })),
  };
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error("The device did not create a credential.");
  const r = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    rawId: bufferToB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufferToB64url(r.clientDataJSON),
      attestationObject: bufferToB64url(r.attestationObject),
      transports: typeof r.getTransports === "function" ? r.getTransports() : [],
    },
    clientExtensionResults: cred.getClientExtensionResults(),
    authenticatorAttachment: (cred as PublicKeyCredential & { authenticatorAttachment?: string }).authenticatorAttachment ?? null,
  };
}

export async function getAssertion(optionsJson: string): Promise<CredentialJSON> {
  const o = JSON.parse(optionsJson);
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...o,
    challenge: b64urlToBuffer(o.challenge),
    allowCredentials: (o.allowCredentials ?? []).map((c: { id: string; type: string; transports?: string[] }) => ({ ...c, id: b64urlToBuffer(c.id) })),
  };
  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No credential was presented.");
  const r = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: bufferToB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufferToB64url(r.clientDataJSON),
      authenticatorData: bufferToB64url(r.authenticatorData),
      signature: bufferToB64url(r.signature),
      userHandle: r.userHandle ? bufferToB64url(r.userHandle) : null,
    },
    clientExtensionResults: cred.getClientExtensionResults(),
    authenticatorAttachment: (cred as PublicKeyCredential & { authenticatorAttachment?: string }).authenticatorAttachment ?? null,
  };
}

import { NextRequest, NextResponse } from "next/server";
import { API_URL } from "@/lib/config";

const ALLOWED_ENDPOINTS = [
  { method: "GET", pathRegex: /^\/api\/test-runs$/ },
  { method: "POST", pathRegex: /^\/api\/test-runs$/ },
  { method: "GET", pathRegex: /^\/api\/test-runs\/[^/]+$/ },
  { method: "DELETE", pathRegex: /^\/api\/test-runs\/[^/]+$/ },
  { method: "POST", pathRegex: /^\/api\/test-runs\/[^/]+\/execute$/ },
  { method: "POST", pathRegex: /^\/api\/test-runs\/[^/]+\/execute-async$/ },
  { method: "GET", pathRegex: /^\/api\/test-runs\/[^/]+\/execution$/ },
  { method: "GET", pathRegex: /^\/api\/test-runs\/[^/]+\/executions$/ },
  { method: "GET", pathRegex: /^\/api\/executions\/[^/]+$/ },
];

function isAllowed(method: string, path: string) {
  return ALLOWED_ENDPOINTS.some(
    (endpoint) => endpoint.method === method && endpoint.pathRegex.test(path)
  );
}

async function handleRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const pathString = `/api/${path.join("/")}`;
  const searchString = request.nextUrl.search;
  
  if (!isAllowed(request.method, pathString)) {
    return NextResponse.json({ detail: "Forbidden proxy route" }, { status: 403 });
  }

  const backendUrl = `${API_URL}${pathString}${searchString}`;
  const apiKey = process.env.MCC_API_KEY || "";

  const headers = new Headers(request.headers);
  headers.set("Authorization", `Bearer ${apiKey}`);
  headers.delete("host"); // Avoid mismatch between proxy host and backend host
  headers.delete("content-length");
  headers.delete("content-encoding");
  headers.delete("connection");
  headers.delete("transfer-encoding");

  const fetchOptions: RequestInit = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    fetchOptions.body = await request.text();
  }

  try {
    const response = await fetch(backendUrl, fetchOptions);

    let bodyData: unknown;
    if (response.status !== 204) {
      const textBody = await response.text();
      try {
        bodyData = textBody ? JSON.parse(textBody) : undefined;
      } catch {
        bodyData = textBody; // Fallback to raw text if not JSON
      }
    }

    const responseHeaders: Record<string, string> = {};
    if (response.headers.has("Retry-After")) {
      responseHeaders["Retry-After"] = response.headers.get("Retry-After")!;
    }

    return NextResponse.json(bodyData, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("Proxy error:", error);
    return NextResponse.json({ detail: "Internal Server Error" }, { status: 500 });
  }
}

export const GET = handleRequest;
export const POST = handleRequest;
export const DELETE = handleRequest;

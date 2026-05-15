import { NextRequest, NextResponse } from "next/server";

const BACKEND = "http://127.0.0.1:8000";

async function proxy(req: NextRequest) {
  const url = req.nextUrl.pathname + (req.nextUrl.search || "");
  const target = BACKEND + url;
  const isBodyless = ["GET", "HEAD"].includes(req.method);

  try {
    const res = await fetch(target, {
      method: req.method,
      headers: {
        ...(req.headers.get("content-type")
          ? { "content-type": req.headers.get("content-type")! }
          : {}),
        accept: req.headers.get("accept") || "*/*",
      },
      body: isBodyless ? undefined : req.body,
      // required when passing a ReadableStream body
      ...(isBodyless ? {} : { duplex: "half" } as object),
    });

    const resHeaders = new Headers();
    const ct = res.headers.get("content-type");
    if (ct) resHeaders.set("content-type", ct);

    return new NextResponse(res.body, { status: res.status, headers: resHeaders });
  } catch (e) {
    console.error("[proxy] error:", e);
    return NextResponse.json({ error: "Backend unreachable", detail: String(e) }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

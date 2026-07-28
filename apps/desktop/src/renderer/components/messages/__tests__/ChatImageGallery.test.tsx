// @vitest-environment jsdom
/**
 * IM 图片消息：缩略图网格 + lightbox（打开 / Esc 关闭 / 下载 / 失败态）。
 * mock fetchChatAttachmentBlob / downloadChatAttachment；桩 createObjectURL。
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

vi.mock("@/services/messaging", () => ({
  fetchChatAttachmentBlob: vi.fn(),
  downloadChatAttachment: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  notifyActionError: vi.fn(),
}));

import type { StoredAttachment } from "@/services/messaging";
import {
  downloadChatAttachment,
  fetchChatAttachmentBlob,
} from "@/services/messaging";
import { ChatImageGallery } from "../ChatImageGallery";

const mockFetch = vi.mocked(fetchChatAttachmentBlob);
const mockDownload = vi.mocked(downloadChatAttachment);

beforeAll(() => {
  URL.createObjectURL = vi.fn(
    () => "blob:mock-im-image",
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
});

beforeEach(() => {
  mockFetch.mockReset();
  mockDownload.mockReset();
  mockFetch.mockResolvedValue(new Blob(["img"], { type: "image/png" }));
  mockDownload.mockResolvedValue(undefined);
});

afterEach(cleanup);

function imageAttachment(
  over: Partial<StoredAttachment> & Pick<StoredAttachment, "name">,
): StoredAttachment {
  return {
    binary: true,
    kind: "file",
    path: over.path ?? `local/${over.name}`,
    truncated: false,
    workspace_path: over.workspace_path ?? `attachments/${over.name}`,
    thumb_path: over.thumb_path ?? null,
    size_bytes: over.size_bytes ?? 1024,
    ...over,
  };
}

describe("ChatImageGallery", () => {
  it("loads thumb preview and opens lightbox on click (original path)", async () => {
    const images = [
      imageAttachment({
        name: "a.png",
        workspace_path: "attachments/a.png",
        thumb_path: "attachments/a.thumb.webp",
      }),
    ];
    render(<ChatImageGallery chatId="chat-1" images={images} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "chat-1",
        "attachments/a.thumb.webp",
      );
    });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(await screen.findByTitle("a.png"));
    expect(screen.getByRole("dialog")).toBeTruthy();

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("chat-1", "attachments/a.png");
    });
  });

  it("closes the lightbox on Escape", async () => {
    const images = [imageAttachment({ name: "solo.jpg" })];
    render(<ChatImageGallery chatId="chat-1" images={images} />);
    fireEvent.click(await screen.findByTitle("solo.jpg"));
    expect(screen.getByRole("dialog")).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("downloads the original from the lightbox toolbar", async () => {
    const images = [
      imageAttachment({
        name: "photo.png",
        workspace_path: "attachments/photo.png",
      }),
    ];
    render(<ChatImageGallery chatId="chat-1" images={images} />);
    fireEvent.click(await screen.findByTitle("photo.png"));

    await waitFor(() => {
      expect(
        screen.getByRole("dialog").querySelector('img[alt="photo.png"]'),
      ).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "下载原图" }));

    await waitFor(() => {
      expect(mockDownload).toHaveBeenCalledWith(
        "chat-1",
        "attachments/photo.png",
        "photo.png",
      );
    });
  });

  it("shows a failed tile when preview fetch rejects", async () => {
    mockFetch.mockRejectedValueOnce(new Error("gone"));
    const images = [imageAttachment({ name: "missing.png" })];
    render(<ChatImageGallery chatId="chat-1" images={images} />);

    expect(await screen.findByLabelText("图片加载失败")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("switches originals with next/prev in a multi-image lightbox", async () => {
    const images = [
      imageAttachment({
        name: "one.png",
        workspace_path: "attachments/one.png",
      }),
      imageAttachment({
        name: "two.png",
        workspace_path: "attachments/two.png",
      }),
    ];
    render(<ChatImageGallery chatId="chat-1" images={images} />);

    fireEvent.click(await screen.findByTitle("one.png"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/one\.png · 1\/2/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "下一张" }));
    expect(screen.getByText(/two\.png · 2\/2/)).toBeTruthy();

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("chat-1", "attachments/two.png");
    });
  });
});

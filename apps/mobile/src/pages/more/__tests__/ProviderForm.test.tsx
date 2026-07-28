// @vitest-environment jsdom
/**
 * Tests for the add / edit BYOK provider form. Covers the preset-prefilled create path and
 * the edit path where an omitted key keeps the stored ciphertext. The REST layer is mocked.
 */
import type { LlmProviderView } from "@/api/llmProviders";
import { createLlmProvider, updateLlmProvider } from "@/api/llmProviders";
import { ProviderForm } from "@/pages/more/ProviderForm";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/llmProviders", () => ({
  createLlmProvider: vi.fn(),
  updateLlmProvider: vi.fn(),
}));

const mockCreate = vi.mocked(createLlmProvider);
const mockUpdate = vi.mocked(updateLlmProvider);

const SAVED: LlmProviderView = {
  id: "prov-1",
  label: "DeepSeek",
  base_url: "https://api.deepseek.com",
  default_model: "deepseek-v4-flash",
  status: "unchecked",
};

afterEach(cleanup);
beforeEach(() => {
  mockCreate.mockReset();
  mockUpdate.mockReset();
});

describe("ProviderForm", () => {
  it("creates a provider from the default preset once a key is entered", async () => {
    mockCreate.mockResolvedValue(SAVED);
    const onSaved = vi.fn();
    render(<ProviderForm onSaved={onSaved} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "sk-test" },
    });
    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith({
      api_key: "sk-test",
      base_url: "https://api.deepseek.com",
      default_model: "deepseek-v4-flash",
      label: "DeepSeek",
    });
    expect(onSaved).toHaveBeenCalledWith(SAVED);
  });

  it("requires a key before the add form can be saved", () => {
    render(<ProviderForm onSaved={vi.fn()} onCancel={vi.fn()} />);
    expect((screen.getByText("保存") as HTMLButtonElement).disabled).toBe(true);
  });

  it("edits an existing provider, keeping the key when left blank", async () => {
    mockUpdate.mockResolvedValue({ ...SAVED, label: "My DeepSeek" });
    const onSaved = vi.fn();
    render(
      <ProviderForm
        provider={{ ...SAVED, label: "My DeepSeek" }}
        onSaved={onSaved}
        onCancel={vi.fn()}
      />,
    );

    // The key field is optional in edit mode; save without touching it.
    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const [id, patch] = mockUpdate.mock.calls[0];
    expect(id).toBe("prov-1");
    expect(patch).not.toHaveProperty("api_key");
    expect(patch.label).toBe("My DeepSeek");
    expect(patch.default_model).toBe("deepseek-v4-flash");
  });
});

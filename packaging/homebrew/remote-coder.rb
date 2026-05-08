class RemoteCoder < Formula
  include Language::Python::Virtualenv

  desc "Telegram-based remote AI coding automation server"
  homepage "https://github.com/YOUR_ORG/remote-coder"
  url "https://files.pythonhosted.org/packages/source/r/remote-coder/remote_coder-0.0.1.tar.gz"
  sha256 "REPLACE_WITH_SDIST_SHA256"
  license "Apache-2.0"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "remote-coder 0.0.1", shell_output("#{bin}/remote-coder --version")
  end
end
